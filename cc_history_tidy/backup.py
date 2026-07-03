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


def create_backup(
    sessions_root: Path,
    backup_parent: Path,
    reason: str,
    config_path: Path | None = None,
) -> BackupSnapshot:
    if not sessions_root.exists():
        raise FileNotFoundError(f"Sessions root does not exist: {sessions_root}")
    created_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    root = backup_parent / created_at
    snapshot_root = root / "claude-code-sessions"
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(sessions_root, snapshot_root)
    snapshot_config_path = None
    if config_path is not None and config_path.exists():
        snapshot_config_path = root / config_path.name
        shutil.copy2(config_path, snapshot_config_path)
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
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return BackupSnapshot(
        root=root,
        sessions_root=sessions_root,
        snapshot_root=snapshot_root,
        manifest_path=manifest_path,
        config_path=config_path,
        snapshot_config_path=snapshot_config_path,
    )


def restore_backup(backup: BackupSnapshot) -> None:
    if not backup.snapshot_root.exists():
        raise FileNotFoundError(f"Backup snapshot does not exist: {backup.snapshot_root}")
    if backup.sessions_root.exists():
        shutil.rmtree(backup.sessions_root)
    shutil.copytree(backup.snapshot_root, backup.sessions_root)
    if backup.config_path is not None and backup.snapshot_config_path is not None:
        if not backup.snapshot_config_path.exists():
            raise FileNotFoundError(f"Backup config snapshot does not exist: {backup.snapshot_config_path}")
        backup.config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup.snapshot_config_path, backup.config_path)


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
    return BackupSnapshot(
        root=root,
        sessions_root=Path(manifest["sessions_root"]),
        snapshot_root=Path(manifest["snapshot_root"]),
        manifest_path=manifest_path,
        config_path=Path(manifest["config_path"]) if manifest.get("config_path") else None,
        snapshot_config_path=Path(manifest["snapshot_config_path"]) if manifest.get("snapshot_config_path") else None,
    )
