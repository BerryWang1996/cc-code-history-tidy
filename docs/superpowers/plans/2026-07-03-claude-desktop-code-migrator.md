# Claude Desktop Code Migrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows Python GUI tool that migrates Claude Desktop Code-mode conversation metadata between local Claude account partitions using copy or move mode, with mandatory backups and restore support.

**Architecture:** The app separates filesystem scanning, session modeling, backup/restore, migration planning, and GUI concerns. The migrator never edits OAuth credentials or JSONL transcript bodies; it only copies or removes Claude Desktop Code session metadata after validation and backup.

**Tech Stack:** Python 3.11+, PySide6, pytest, pytest-qt, PyInstaller, standard-library `json`, `pathlib`, `shutil`, `hashlib`, and `datetime`.

---

## File Structure

- Create `pyproject.toml`: package metadata, dependencies, pytest config, console entry point.
- Create `README.md`: usage, safety model, backup/restore notes, Windows path discovery.
- Create `cc_history_tidy/__init__.py`: package marker and version.
- Create `cc_history_tidy/models.py`: dataclasses for accounts, sessions, backups, migration plans, and results.
- Create `cc_history_tidy/paths.py`: adaptive discovery for Claude config, transcript root, and `claude-code-sessions` roots.
- Create `cc_history_tidy/scanner.py`: account/session scanner that reads metadata JSON and validates linked JSONL existence.
- Create `cc_history_tidy/backup.py`: backup manifest writer, snapshot copier, and restore helper.
- Create `cc_history_tidy/migrator.py`: dry-run, copy migration, safe move migration, conflict handling.
- Create `cc_history_tidy/gui.py`: PySide6 main window, tree views, migration queue, backup/restore controls.
- Create `cc_history_tidy/main.py`: app entry point.
- Create `tests/fixtures.py`: temporary Claude Desktop fixture builder.
- Create `tests/test_paths.py`: path discovery tests.
- Create `tests/test_scanner.py`: scanner tests.
- Create `tests/test_backup.py`: backup and restore tests.
- Create `tests/test_migrator.py`: copy/move/dry-run/conflict tests.
- Create `tests/test_gui_smoke.py`: minimal GUI import/start smoke test.

## Task 1: Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `cc_history_tidy/__init__.py`
- Create: `cc_history_tidy/main.py`
- Create: `tests/test_import.py`

- [ ] **Step 1: Write the failing import test**

```python
def test_package_imports():
    import cc_history_tidy

    assert isinstance(cc_history_tidy.__version__, str)
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_import.py -v`
Expected: FAIL because `cc_history_tidy` does not exist.

- [ ] **Step 3: Create project metadata and minimal package**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=70", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "cc-code-history-tidy"
version = "0.1.0"
description = "Claude Desktop Code history migration tool"
requires-python = ">=3.11"
dependencies = [
  "PySide6>=6.7",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-qt>=4.4",
  "pyinstaller>=6.0",
]

[project.scripts]
cc-history-tidy = "cc_history_tidy.main:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`cc_history_tidy/__init__.py`:

```python
__version__ = "0.1.0"
```

`cc_history_tidy/main.py`:

```python
def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `python -m pytest tests/test_import.py -v`
Expected: PASS.

## Task 2: Domain Models

**Files:**
- Create: `cc_history_tidy/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write model tests**

```python
from pathlib import Path

from cc_history_tidy.models import AccountPartition, ClaudeSession, MigrationMode


def test_account_hash_does_not_expose_uuid():
    account = AccountPartition(
        account_uuid="11111111-2222-3333-4444-555555555555",
        root=Path("accounts/source"),
        is_current=False,
    )

    assert account.display_name.startswith("Account ")
    assert "11111111" not in account.display_name


def test_session_can_report_missing_transcript():
    session = ClaudeSession(
        metadata_path=Path("session.json"),
        account_uuid="source",
        session_id="desktop-session",
        cli_session_id="cli-session",
        title="A title",
        cwd="C:/work/project",
        created_at=1,
        last_activity_at=2,
        archived=False,
        transcript_path=None,
    )

    assert not session.has_transcript
    assert MigrationMode.COPY.value == "copy"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL because models are missing.

- [ ] **Step 3: Implement dataclasses and enums**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib


class MigrationMode(str, Enum):
    COPY = "copy"
    MOVE = "move"


@dataclass(frozen=True)
class AccountPartition:
    account_uuid: str
    root: Path
    is_current: bool

    @property
    def display_name(self) -> str:
        digest = hashlib.sha256(self.account_uuid.encode("utf-8")).hexdigest()[:8].upper()
        suffix = "current" if self.is_current else "source"
        return f"Account {digest} ({suffix})"


@dataclass(frozen=True)
class ClaudeSession:
    metadata_path: Path
    account_uuid: str
    session_id: str
    cli_session_id: str
    title: str
    cwd: str
    created_at: int | None
    last_activity_at: int | None
    archived: bool
    transcript_path: Path | None

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path is not None and self.transcript_path.exists()


@dataclass(frozen=True)
class MigrationItem:
    source: ClaudeSession
    target_metadata_path: Path


@dataclass(frozen=True)
class MigrationPlan:
    mode: MigrationMode
    target_account: AccountPartition
    items: tuple[MigrationItem, ...]


@dataclass(frozen=True)
class MigrationResult:
    copied: tuple[Path, ...]
    removed: tuple[Path, ...]
    backup_root: Path
```

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS.

## Task 3: Fixture Builder and Path Discovery

**Files:**
- Create: `tests/fixtures.py`
- Create: `cc_history_tidy/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write path discovery tests**

```python
from pathlib import Path

from tests.fixtures import build_claude_fixture
from cc_history_tidy.paths import discover_claude_environment


def test_discover_environment_from_fixture(tmp_path):
    fixture = build_claude_fixture(tmp_path)

    env = discover_claude_environment(
        user_profile=fixture.user_profile,
        appdata=fixture.appdata,
        localappdata=fixture.localappdata,
    )

    assert env.current_account_uuid == fixture.current_account_uuid
    assert env.transcript_root == fixture.user_profile / ".claude" / "projects"
    assert env.sessions_root == fixture.sessions_root
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_paths.py -v`
Expected: FAIL because fixture and discovery code are missing.

- [ ] **Step 3: Implement fixture builder**

`tests/fixtures.py` creates a fake user profile, `.claude.json`, `.claude/projects`, and a package-style Claude root with `claude-code-sessions/<accountUuid>`.

- [ ] **Step 4: Implement adaptive discovery**

`discover_claude_environment()` must:
- read `.claude.json` from the supplied user profile,
- parse `oauthAccount.accountUuid`,
- find `claude-code-sessions` under known Claude Desktop roots,
- prefer the root containing the current account UUID,
- return a typed environment object with paths.

- [ ] **Step 5: Run tests and verify pass**

Run: `python -m pytest tests/test_paths.py -v`
Expected: PASS.

## Task 4: Session Scanner

**Files:**
- Create: `cc_history_tidy/scanner.py`
- Test: `tests/test_scanner.py`

- [ ] **Step 1: Write scanner tests**

```python
from tests.fixtures import build_claude_fixture
from cc_history_tidy.paths import discover_claude_environment
from cc_history_tidy.scanner import scan_accounts


def test_scanner_lists_current_and_source_sessions(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(fixture.user_profile, fixture.appdata, fixture.localappdata)

    accounts = scan_accounts(env)

    assert len(accounts) == 2
    sessions = [session for account in accounts for session in account.sessions]
    assert {session.cli_session_id for session in sessions} == {"cli-current", "cli-source"}
    assert all(session.has_transcript for session in sessions)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: FAIL because scanner is missing.

- [ ] **Step 3: Implement scanner**

The scanner should recursively parse `*.json` metadata under each account UUID directory, read `sessionId`, `cliSessionId`, `title`, `cwd`, timestamps, and locate `cliSessionId.jsonl` below `.claude/projects`.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: PASS.

## Task 5: Backup and Restore

**Files:**
- Create: `cc_history_tidy/backup.py`
- Test: `tests/test_backup.py`

- [ ] **Step 1: Write backup tests**

```python
from tests.fixtures import build_claude_fixture
from cc_history_tidy.backup import create_backup, restore_backup


def test_backup_and_restore_sessions_root(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"

    backup = create_backup(fixture.sessions_root, backup_root, reason="unit-test")
    source_file = fixture.sessions_root / fixture.source_account_uuid / "session-source.json"
    source_file.unlink()

    restore_backup(backup)

    assert source_file.exists()
    assert (backup.root / "backup-manifest.json").exists()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_backup.py -v`
Expected: FAIL because backup code is missing.

- [ ] **Step 3: Implement backup snapshot and manifest**

`create_backup()` copies the full `claude-code-sessions` tree into a timestamped backup directory and writes `backup-manifest.json`. `restore_backup()` replaces the sessions root from the snapshot after making sure the snapshot exists.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_backup.py -v`
Expected: PASS.

## Task 6: Migration Engine

**Files:**
- Create: `cc_history_tidy/migrator.py`
- Test: `tests/test_migrator.py`

- [ ] **Step 1: Write migration tests**

```python
from tests.fixtures import build_claude_fixture
from cc_history_tidy.migrator import migrate_sessions
from cc_history_tidy.models import MigrationMode


def test_copy_migration_keeps_source_metadata(tmp_path):
    fixture = build_claude_fixture(tmp_path)

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[fixture.sessions_root / fixture.source_account_uuid / "session-source.json"],
        mode=MigrationMode.COPY,
        backup_root=tmp_path / "backups",
    )

    assert result.copied
    assert not result.removed
    assert (fixture.sessions_root / fixture.source_account_uuid / "session-source.json").exists()
    assert (fixture.sessions_root / fixture.current_account_uuid / "session-source.json").exists()


def test_move_migration_removes_source_after_copy(tmp_path):
    fixture = build_claude_fixture(tmp_path)

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[fixture.sessions_root / fixture.source_account_uuid / "session-source.json"],
        mode=MigrationMode.MOVE,
        backup_root=tmp_path / "backups",
    )

    assert result.copied
    assert result.removed
    assert not (fixture.sessions_root / fixture.source_account_uuid / "session-source.json").exists()
    assert (fixture.sessions_root / fixture.current_account_uuid / "session-source.json").exists()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_migrator.py -v`
Expected: FAIL because migrator is missing.

- [ ] **Step 3: Implement safe copy and safe move**

The migrator must create a backup first, reject target file conflicts, copy selected metadata files, parse copied JSON to verify `sessionId` and `cliSessionId`, and only delete source files in move mode after verification.

- [ ] **Step 4: Run tests and verify pass**

Run: `python -m pytest tests/test_migrator.py -v`
Expected: PASS.

## Task 7: GUI

**Files:**
- Create: `cc_history_tidy/gui.py`
- Modify: `cc_history_tidy/main.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write GUI smoke test**

```python
from cc_history_tidy.gui import create_app, MainWindow


def test_main_window_constructs(qtbot):
    app = create_app([])
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_gui_smoke.py -v`
Expected: FAIL because GUI is missing.

- [ ] **Step 3: Implement minimal PySide6 window**

The first GUI pass should show source account tree, target account tree, migration mode radio buttons, dry-run button, migrate button, backup button, and status log. Drag-and-drop can be implemented as queue buttons in the first commit if direct drag support slows delivery.

- [ ] **Step 4: Run GUI smoke test**

Run: `python -m pytest tests/test_gui_smoke.py -v`
Expected: PASS.

## Task 8: Documentation and Packaging

**Files:**
- Modify: `README.md`
- Create: `scripts/build_exe.ps1`

- [ ] **Step 1: Document safety model**

README must state that the app only migrates Claude Desktop Code metadata, does not touch OAuth or JSONL transcript bodies, and creates mandatory backups before writes.

- [ ] **Step 2: Add PyInstaller build script**

`scripts/build_exe.ps1` should run:

```powershell
python -m PyInstaller --name cc-code-history-tidy --windowed --onefile -m cc_history_tidy.main
```

- [ ] **Step 3: Run full verification**

Run: `python -m pytest -v`
Expected: PASS.

- [ ] **Step 4: Build executable**

Run: `powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1`
Expected: `dist/cc-code-history-tidy.exe` exists.

## Self-Review

- Spec coverage: copy mode, move mode, backup, restore, adaptive path discovery, conflict blocking, no OAuth edits, no JSONL body edits, GUI tree/queue, and packaging are covered.
- Placeholder scan: no task relies on undefined behavior; GUI drag-and-drop may be delivered as a queued selection first, with direct drag as a follow-up if needed.
- Type consistency: account/session/migration models are introduced before scanner, backup, migrator, and GUI tasks use them.
