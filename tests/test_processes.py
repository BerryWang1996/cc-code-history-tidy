from pathlib import Path

from cc_history_tidy import processes
from cc_history_tidy.processes import claude_lock_paths, is_claude_desktop_running


def _make_lock(root: Path) -> Path:
    lock = root / "Claude" / "Local Storage" / "leveldb" / "LOCK"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b"")
    return lock


def test_lock_paths_found_and_deduplicated(tmp_path):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    lock = _make_lock(appdata)
    (localappdata / "Claude-3p" / "Local Storage" / "leveldb").mkdir(parents=True)
    lock3p = localappdata / "Claude-3p" / "Local Storage" / "leveldb" / "LOCK"
    lock3p.write_bytes(b"")

    paths = claude_lock_paths(appdata=appdata, localappdata=localappdata)

    assert lock in paths and lock3p in paths
    assert len(paths) == len(set(p.resolve() for p in paths))


def test_running_check_false_when_locks_free(tmp_path, monkeypatch):
    monkeypatch.setattr(processes.os, "name", "nt")
    lock = _make_lock(tmp_path)

    assert is_claude_desktop_running(lock_paths=[lock]) is False


def test_running_check_true_when_lock_held(tmp_path, monkeypatch):
    monkeypatch.setattr(processes.os, "name", "nt")
    lock = _make_lock(tmp_path)
    monkeypatch.setattr(processes, "_lock_is_held", lambda path: True)

    assert is_claude_desktop_running(lock_paths=[lock]) is True


def test_running_check_false_off_windows(monkeypatch):
    monkeypatch.setattr(processes.os, "name", "posix")
    assert is_claude_desktop_running() is False
