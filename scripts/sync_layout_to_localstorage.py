"""One-shot repair: push each Claude root's config group layout into the
renderer's Local Storage (LevelDB).

Use when a migration was executed with a tool version that only wrote
claude_desktop_config.json: the sidebar reads group definitions from the
renderer store, so migrated groups rendered as ungrouped. Running this after
closing Claude Desktop makes the renderer state match the config.

Usage:
    .venv/Scripts/python.exe scripts/sync_layout_to_localstorage.py [--dry-run]
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cc_history_tidy.code_groups import (  # noqa: E402
    _custom_group_labels,
    _list_dict,
    _read_desktop_slice,
    _string_dict,
    save_code_group_layout_to_local_storage,
)


def claude_roots() -> list[Path]:
    appdata = Path(os.environ["APPDATA"])
    localappdata = Path(os.environ["LOCALAPPDATA"])
    candidates = [appdata / "Claude", localappdata / "Claude", localappdata / "Claude-3p"]
    packages = localappdata / "Packages"
    if packages.exists():
        for package_dir in packages.glob("Claude_*"):
            candidates.append(package_dir / "LocalCache" / "Roaming" / "Claude")
    seen: set[Path] = set()
    roots: list[Path] = []
    for root in candidates:
        if not root.is_dir():
            continue
        try:
            physical = root.resolve()
        except OSError:
            physical = root
        if physical in seen:
            continue
        seen.add(physical)
        roots.append(root)
    return roots


def ensure_unlocked(leveldb_dir: Path) -> bool:
    lock = leveldb_dir / "LOCK"
    if not lock.exists():
        return True
    try:
        handle = open(lock, "r+b")
        handle.close()
        return True
    except OSError:
        return False


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    backup_parent = (
        Path(os.environ.get("USERPROFILE", str(Path.home())))
        / ".claude-desktop-migrator"
        / "backups"
    )
    any_written = False
    for root in claude_roots():
        slice_data = _read_desktop_slice(root / "claude_desktop_config.json")
        assignments = _string_dict(slice_data.get("customGroupAssignments"))
        order_data = {k: list(v) for k, v in _list_dict(slice_data.get("customGroupOrder")).items()}
        labels = _custom_group_labels(slice_data.get("customGroups"))
        leveldb_dir = root / "Local Storage" / "leveldb"
        if not leveldb_dir.is_dir():
            continue
        if not (assignments or order_data):
            print(f"[skip] {root}: config carries no group layout")
            continue
        if not ensure_unlocked(leveldb_dir):
            print(f"[LOCKED] {root}: close Claude Desktop first")
            continue
        if dry_run:
            print(f"[dry-run] {root}: would sync {len(assignments)} assignment(s), "
                  f"{len(order_data)} group(s), {len(labels)} label(s)")
            continue
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = backup_parent / f"{stamp}-localstorage-sync" / "local-storage-leveldb"
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(leveldb_dir, backup_dir)
        # Config assignments are authoritative: purge every key known to either
        # store, then apply the config's.
        wrote = save_code_group_layout_to_local_storage(
            root,
            visible_session_keys=set(assignments),
            assignments=assignments,
            order_data=order_data,
            group_labels=labels,
        )
        state = "synced" if wrote else "no renderer store"
        print(f"[{state}] {root} (backup: {backup_dir.parent})")
        any_written = any_written or wrote
    if not any_written and not dry_run:
        print("Nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
