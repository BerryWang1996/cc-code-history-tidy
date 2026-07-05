from __future__ import annotations

import os
from pathlib import Path


def claude_lock_paths(
    appdata: Path | None = None,
    localappdata: Path | None = None,
) -> list[Path]:
    """LevelDB LOCK files of every known Claude Desktop install root.

    While Claude Desktop runs it keeps its localStorage LevelDB open, holding
    the LOCK file without share access. Probing these files is both faster
    than spawning ``tasklist`` and more precise: the Claude Code CLI (which
    also runs as ``claude.exe``) holds no such lock and no longer blocks
    Execute.
    """
    appdata = appdata or Path(os.environ.get("APPDATA", ""))
    localappdata = localappdata or Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        appdata / "Claude",
        localappdata / "Claude",
        localappdata / "Claude-3p",
    ]
    packages = localappdata / "Packages"
    if packages.exists():
        for package_dir in packages.glob("Claude_*"):
            candidates.append(package_dir / "LocalCache" / "Roaming" / "Claude")

    locks: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        lock = root / "Local Storage" / "leveldb" / "LOCK"
        if not lock.exists():
            continue
        try:
            physical = lock.resolve()
        except OSError:
            physical = lock
        if physical in seen:
            continue
        seen.add(physical)
        locks.append(lock)
    return locks


def _lock_is_held(lock: Path) -> bool:
    try:
        handle = open(lock, "r+b")
    except PermissionError:
        return True
    except OSError as exc:
        # WinError 32: sharing violation — leveldb opened it with no share mode.
        return getattr(exc, "winerror", None) == 32
    handle.close()
    return False


def is_claude_desktop_running(lock_paths: list[Path] | None = None) -> bool:
    if os.name != "nt":
        return False
    paths = claude_lock_paths() if lock_paths is None else lock_paths
    return any(_lock_is_held(lock) for lock in paths)
