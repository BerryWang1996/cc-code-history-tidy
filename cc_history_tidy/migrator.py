from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid

from cc_history_tidy.backup import BackupSnapshot, create_backup
from cc_history_tidy.models import MigrationMode, MigrationResult


class MigrationConflictError(RuntimeError):
    pass


def migrate_sessions(
    sessions_root: Path,
    source_account_uuid: str,
    target_account_uuid: str,
    session_files: list[Path],
    mode: MigrationMode,
    backup_root: Path,
    target_group_id: str,
    config_path: Path | None = None,
    target_sessions_root: Path | None = None,
    reuse_backup: BackupSnapshot | None = None,
) -> MigrationResult:
    if not session_files:
        raise ValueError("At least one session metadata file is required")
    if not target_group_id:
        raise ValueError(
            "target_group_id must not be empty: sessions must live under "
            "claude-code-sessions/<account>/<group>/, never directly under the account root"
        )
    if mode not in (MigrationMode.COPY, MigrationMode.MOVE):
        raise ValueError(f"Unsupported migration mode: {mode}")

    source_root = sessions_root / source_account_uuid
    target_root = (target_sessions_root or sessions_root) / target_account_uuid

    rewrite_ids = mode == MigrationMode.COPY
    copy_pairs = _build_copy_pairs(source_root, target_root, session_files, target_group_id, rewrite_ids)
    conflicts = [target for _, target, _ in copy_pairs if target.exists()]
    if conflicts:
        raise MigrationConflictError(f"Target metadata already exists: {conflicts[0]}")
    if mode == MigrationMode.MOVE:
        # COPY is protected by the sessionId rewrite; a MOVE carries its id
        # along, so the same id must not already live anywhere in the target
        # root (group assignments are keyed code:<sessionId> per root).
        _ensure_no_duplicate_session_ids(copy_pairs, target_sessions_root or sessions_root)

    if reuse_backup is not None:
        backup = reuse_backup
    else:
        backup = create_backup(sessions_root, backup_root, reason=f"migration-{mode.value}", config_path=config_path)

    target_root.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    removed: list[Path] = []

    for source, target, new_session_id in copy_pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if new_session_id is None:
            shutil.copy2(source, target)
        else:
            _copy_with_new_session_id(source, target, new_session_id)
        _verify_copied_metadata(source, target, new_session_id)
        copied.append(target)

    if mode == MigrationMode.MOVE:
        for source, _, _ in copy_pairs:
            source.unlink()
            removed.append(source)
        _prune_empty_dirs({source.parent for source, _, _ in copy_pairs}, stop_at=sessions_root)

    return MigrationResult(
        copied=tuple(copied),
        removed=tuple(removed),
        backup_root=backup.root,
    )


def _build_copy_pairs(
    source_root: Path,
    target_root: Path,
    session_files: list[Path],
    target_group_id: str,
    rewrite_ids: bool,
) -> list[tuple[Path, Path, str | None]]:
    pairs: list[tuple[Path, Path, str | None]] = []
    seen_targets: set[Path] = set()
    for raw_source in session_files:
        source = Path(raw_source)
        if not source.exists():
            raise FileNotFoundError(f"Session metadata does not exist: {source}")
        try:
            relative = source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"Session metadata is not inside source account: {source}") from exc
        source_session_id, _ = _read_metadata_identity(source)
        new_session_id = None
        if rewrite_ids and source_session_id:
            new_session_id = _new_session_id_for(source_session_id)
        target_name = source.name
        if new_session_id is not None and source.stem == source_session_id:
            # Real Claude Desktop files are named <sessionId>.json; keep that invariant.
            target_name = f"{new_session_id}{source.suffix}"
        if len(relative.parts) > 1:
            target_relative = Path(target_group_id, *relative.parts[1:-1], target_name)
        else:
            target_relative = Path(target_group_id, target_name)
        target = target_root / target_relative
        if target in seen_targets:
            raise MigrationConflictError(
                f"Two selected sessions map to the same target file: {target}"
            )
        seen_targets.add(target)
        pairs.append((source, target, new_session_id))
    return pairs


def _new_session_id_for(source_session_id: str) -> str:
    fresh = str(uuid.uuid4())
    if "_" in source_session_id:
        prefix = source_session_id.rsplit("_", 1)[0]
        return f"{prefix}_{fresh}"
    return fresh


def _ensure_no_duplicate_session_ids(
    copy_pairs: list[tuple[Path, Path, str | None]],
    target_sessions_root: Path,
) -> None:
    moving_ids = {}
    for source, _, _ in copy_pairs:
        session_id, _ = _read_metadata_identity(source)
        if session_id:
            moving_ids[session_id] = source
    if not moving_ids or not target_sessions_root.exists():
        return
    moving_sources = {source for source, _, _ in copy_pairs}
    for metadata_path in target_sessions_root.rglob("*.json"):
        if metadata_path in moving_sources:
            continue
        try:
            existing_id, _ = _read_metadata_identity(metadata_path)
        except (OSError, json.JSONDecodeError):
            continue
        if existing_id and existing_id in moving_ids:
            raise MigrationConflictError(
                f"Session id {existing_id} already exists in the target root: {metadata_path}"
            )


def _copy_with_new_session_id(source: Path, target: Path, new_session_id: str) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    data["sessionId"] = new_session_id
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copystat(source, target)


def _prune_empty_dirs(dirs: set[Path], stop_at: Path) -> None:
    for directory in dirs:
        current = directory
        while current != stop_at and stop_at in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def _verify_copied_metadata(source: Path, target: Path, new_session_id: str | None) -> None:
    source_identity = _read_metadata_identity(source)
    target_identity = _read_metadata_identity(target)
    expected = (new_session_id or source_identity[0], source_identity[1])
    if target_identity != expected:
        raise RuntimeError(f"Copied metadata identity mismatch: {source} -> {target}")


def _read_metadata_identity(path: Path) -> tuple[str | None, str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None, None
    return data.get("sessionId"), data.get("cliSessionId")
