from __future__ import annotations

import json
from pathlib import Path
import shutil

from cc_history_tidy.backup import create_backup
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
) -> MigrationResult:
    if not session_files:
        raise ValueError("At least one session metadata file is required")

    source_root = sessions_root / source_account_uuid
    target_root = sessions_root / target_account_uuid
    target_root.mkdir(parents=True, exist_ok=True)

    copy_pairs = _build_copy_pairs(source_root, target_root, session_files, target_group_id)
    conflicts = [target for _, target in copy_pairs if target.exists()]
    if conflicts:
        raise MigrationConflictError(f"Target metadata already exists: {conflicts[0]}")

    backup = create_backup(sessions_root, backup_root, reason=f"migration-{mode.value}", config_path=config_path)
    copied: list[Path] = []
    removed: list[Path] = []

    for source, target in copy_pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        _verify_copied_metadata(source, target)
        copied.append(target)

    if mode == MigrationMode.MOVE:
        for source, _ in copy_pairs:
            source.unlink()
            removed.append(source)
    elif mode != MigrationMode.COPY:
        raise ValueError(f"Unsupported migration mode: {mode}")

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
) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for raw_source in session_files:
        source = Path(raw_source)
        if not source.exists():
            raise FileNotFoundError(f"Session metadata does not exist: {source}")
        try:
            relative = source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"Session metadata is not inside source account: {source}") from exc
        if len(relative.parts) > 1:
            target_relative = Path(target_group_id, *relative.parts[1:])
        else:
            target_relative = Path(target_group_id, relative.name)
        pairs.append((source, target_root / target_relative))
    return pairs


def _verify_copied_metadata(source: Path, target: Path) -> None:
    source_identity = _read_metadata_identity(source)
    target_identity = _read_metadata_identity(target)
    if source_identity != target_identity:
        raise RuntimeError(f"Copied metadata identity mismatch: {source} -> {target}")


def _read_metadata_identity(path: Path) -> tuple[str | None, str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("sessionId"), data.get("cliSessionId")
