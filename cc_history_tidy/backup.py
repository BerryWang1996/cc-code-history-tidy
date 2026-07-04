from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil


@dataclass(frozen=True)
class BackupSnapshot:
    root: Path
    sessions_root: Path
    snapshot_root: Path
    manifest_path: Path
    config_path: Path | None = None
    snapshot_config_path: Path | None = None
    local_storage_path: Path | None = None
    snapshot_local_storage_path: Path | None = None
    reason: str = ""


def create_backup(
    sessions_root: Path,
    backup_parent: Path,
    reason: str,
    config_path: Path | None = None,
) -> BackupSnapshot:
    if not sessions_root.exists():
        raise FileNotFoundError(f"Sessions root does not exist: {sessions_root}")
    base_name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    created_at = base_name
    suffix = 1
    while True:
        root = backup_parent / created_at
        try:
            root.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            # Two backups within the same clock tick (e.g. one per involved
            # root during a single execute) must not collide.
            created_at = f"{base_name}-{suffix}"
            suffix += 1
    snapshot_root = root / "claude-code-sessions"
    # The renderer's localStorage (LevelDB) is written during execute too, so
    # it must be part of the same rollback unit.
    local_storage_path = sessions_root.parent / "Local Storage" / "leveldb"
    try:
        shutil.copytree(sessions_root, snapshot_root)
        snapshot_config_path = None
        if config_path is not None and config_path.exists():
            snapshot_config_path = root / config_path.name
            shutil.copy2(config_path, snapshot_config_path)
        snapshot_local_storage_path = None
        if local_storage_path.is_dir():
            snapshot_local_storage_path = root / "local-storage-leveldb"
            shutil.copytree(local_storage_path, snapshot_local_storage_path)
        manifest_path = root / "backup-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "created_at": created_at,
                    "reason": reason,
                    "sessions_root": str(sessions_root),
                    "snapshot_root": str(snapshot_root),
                    "config_path": str(config_path) if config_path is not None else None,
                    "snapshot_config_path": str(snapshot_config_path) if snapshot_config_path is not None else None,
                    "local_storage_path": str(local_storage_path),
                    "snapshot_local_storage_path": (
                        str(snapshot_local_storage_path) if snapshot_local_storage_path is not None else None
                    ),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except BaseException:
        # Never leave a half-written snapshot that looks like a valid backup.
        shutil.rmtree(root, ignore_errors=True)
        raise
    return BackupSnapshot(
        root=root,
        sessions_root=sessions_root,
        snapshot_root=snapshot_root,
        manifest_path=manifest_path,
        config_path=config_path,
        snapshot_config_path=snapshot_config_path,
        local_storage_path=local_storage_path,
        snapshot_local_storage_path=snapshot_local_storage_path,
        reason=reason,
    )


def restore_backup(backup: BackupSnapshot) -> None:
    if not backup.snapshot_root.exists():
        raise FileNotFoundError(f"Backup snapshot does not exist: {backup.snapshot_root}")

    sessions_root = backup.sessions_root
    staging = sessions_root.parent / f"{sessions_root.name}.restore-staging"
    displaced = sessions_root.parent / f"{sessions_root.name}.restore-displaced"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(displaced, ignore_errors=True)

    # Stage the snapshot copy first so the live tree is only touched by two renames.
    shutil.copytree(backup.snapshot_root, staging)
    try:
        if sessions_root.exists():
            sessions_root.rename(displaced)
        try:
            staging.rename(sessions_root)
        except OSError:
            if displaced.exists():
                displaced.rename(sessions_root)
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(displaced, ignore_errors=True)

    if backup.config_path is not None:
        if backup.snapshot_config_path is not None:
            if not backup.snapshot_config_path.exists():
                raise FileNotFoundError(
                    f"Backup config snapshot does not exist: {backup.snapshot_config_path}"
                )
            backup.config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup.snapshot_config_path, backup.config_path)
        elif backup.config_path.exists():
            # The config was tracked but did not exist when the backup was
            # taken; a file present now was created by the failed run and must
            # go away with the rollback.
            backup.config_path.unlink()

    if backup.local_storage_path is not None and backup.snapshot_local_storage_path is not None:
        if backup.snapshot_local_storage_path.exists():
            _swap_dir_from_snapshot(backup.snapshot_local_storage_path, backup.local_storage_path)


def _swap_dir_from_snapshot(snapshot_dir: Path, live_dir: Path) -> None:
    staging = live_dir.parent / f"{live_dir.name}.restore-staging"
    displaced = live_dir.parent / f"{live_dir.name}.restore-displaced"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(displaced, ignore_errors=True)
    shutil.copytree(snapshot_dir, staging)
    try:
        if live_dir.exists():
            live_dir.rename(displaced)
        try:
            staging.rename(live_dir)
        except OSError:
            if displaced.exists():
                displaced.rename(live_dir)
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(displaced, ignore_errors=True)


def list_backups(backup_parent: Path) -> list[BackupSnapshot]:
    if not backup_parent.exists():
        return []
    backups: list[BackupSnapshot] = []
    for manifest_path in backup_parent.glob("*/backup-manifest.json"):
        try:
            backups.append(load_backup(manifest_path.parent))
        except (OSError, KeyError, json.JSONDecodeError):
            continue
    return sorted(backups, key=lambda backup: backup.root.name, reverse=True)


def load_backup(root: Path) -> BackupSnapshot:
    manifest_path = root / "backup-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # The backup directory may have been moved since creation; prefer the
    # snapshot that actually sits next to the manifest over the recorded
    # absolute path.
    local_snapshot = root / "claude-code-sessions"
    snapshot_root = local_snapshot if local_snapshot.exists() else Path(manifest["snapshot_root"])
    snapshot_config_path = None
    if manifest.get("snapshot_config_path"):
        recorded = Path(manifest["snapshot_config_path"])
        local_config = root / recorded.name
        snapshot_config_path = local_config if local_config.exists() else recorded
    snapshot_local_storage_path = None
    if manifest.get("snapshot_local_storage_path"):
        recorded = Path(manifest["snapshot_local_storage_path"])
        local_ls = root / "local-storage-leveldb"
        snapshot_local_storage_path = local_ls if local_ls.exists() else recorded
    return BackupSnapshot(
        root=root,
        sessions_root=Path(manifest["sessions_root"]),
        snapshot_root=snapshot_root,
        manifest_path=manifest_path,
        config_path=Path(manifest["config_path"]) if manifest.get("config_path") else None,
        snapshot_config_path=snapshot_config_path,
        local_storage_path=(
            Path(manifest["local_storage_path"]) if manifest.get("local_storage_path") else None
        ),
        snapshot_local_storage_path=snapshot_local_storage_path,
        reason=str(manifest.get("reason") or ""),
    )
