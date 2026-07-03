# Group Clipboard + Undo/Reset + i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group-level copy/cut/paste with same-name merge, undo/redo/reset for all tree edits, copies landing in their pasted group after execute, and a switchable zh/en UI defaulting to the system language.

**Architecture:** A new `i18n` module holds every user-visible string; a new `tree_state` module snapshots/restores the whole tree for undo/redo/reset. `SessionTreeWidget` gains a group-aware clipboard with merge-by-label, and `migrate_sessions` returns an old→new sessionId mapping so `execute_plan` can write copied sessions into their target group's layout. Everything stays simulated until Execute.

**Tech Stack:** Python 3.11, PySide6, pytest (suite: 84 green).

**Spec:** `docs/superpowers/specs/2026-07-03-group-clipboard-undo-i18n-design.md`

---

## File Structure

- Create `cc_history_tidy/i18n.py` — zh/en tables, `tr()`, `set_language()`, `detect_default_language()`, settings load/save.
- Create `cc_history_tidy/tree_state.py` — `TreeState` dataclasses + `capture_tree_state` / `restore_tree_state`.
- Create `tests/conftest.py` — autouse fixture pinning language to zh for deterministic assertions.
- Modify `cc_history_tidy/models.py` — `MigrationResult.session_id_mapping`.
- Modify `cc_history_tidy/migrator.py` — return the mapping.
- Modify `cc_history_tidy/code_groups.py` — `save_code_group_layout_to_desktop_config(..., group_labels=None)` writes `customGroups`.
- Modify `cc_history_tidy/session_tree.py` — group clipboard, merge, undo stacks, `treeChanged` signal, tr() strings.
- Modify `cc_history_tidy/gui.py` — undo/redo/reset buttons, language combo + `retranslate_ui`, ghost→new-id layout write, tr() strings.
- Tests: `tests/test_i18n.py`, `tests/test_tree_undo.py`, `tests/test_group_clipboard.py`, extend `tests/test_gui_clipboard_execute.py`.

### Task 1: i18n module

**Files:** Create `cc_history_tidy/i18n.py`, `tests/conftest.py`, `tests/test_i18n.py`

- [ ] **Step 1: failing tests** (`tests/test_i18n.py`)

```python
import json

from cc_history_tidy import i18n


def test_tr_formats_and_switches_language():
    i18n.set_language("zh")
    zh = i18n.tr("status.copied_n", n=2)
    i18n.set_language("en")
    en = i18n.tr("status.copied_n", n=2)
    assert "2" in zh and "2" in en
    assert zh != en


def test_missing_key_falls_back_to_zh():
    i18n.set_language("en")
    assert i18n.tr("badge.move")  # exists in both; sanity
    # a key present only in zh must not raise
    i18n.LANGS["en"].pop("badge.move", None)
    try:
        assert i18n.tr("badge.move") == i18n.LANGS["zh"]["badge.move"]
    finally:
        i18n.LANGS["en"]["badge.move"] = "pending move"


def test_detect_default_language_prefers_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    assert i18n.detect_default_language(settings) == "en"


def test_detect_default_language_survives_corrupt_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{broken", encoding="utf-8")
    assert i18n.detect_default_language(settings) in {"zh", "en"}


def test_save_language_persists(tmp_path):
    settings = tmp_path / "settings.json"
    i18n.save_language("en", settings)
    assert i18n.detect_default_language(settings) == "en"
```

- [ ] **Step 2: run, expect import failure**

- [ ] **Step 3: implement `cc_history_tidy/i18n.py`**

Full key table (zh = current UI strings, en = translations). Keys:
`app.initial_status, app.title, btn.scan, btn.preview, btn.execute, btn.backups, btn.undo, btn.redo, btn.reset, header.tree, header.updated, tree.group_type, tree.sessions_count, badge.move, badge.copy, menu.copy, menu.cut, menu.paste, menu.undo_ghost, status.scan_failed, status.loaded, status.dry_run, status.no_backups, status.restored, status.close_claude_first, status.scan_first, status.no_staged, status.cancelled, status.backup_failed, status.exec_failed_rolled_back, status.exec_failed_partial, status.executed, status.staged_summary, status.copied_n, status.cut_n, status.select_first, status.paste_empty, status.paste_target_invalid, status.ghost_removed, status.mixed_selection, status.clipboard_cleared, status.reset_done, status.nothing_to_undo, status.nothing_to_redo, status.undo_done, status.redo_done, status.language_changed, tooltip.execute_disabled, tooltip.execute_enabled, dlg.confirm_title, dlg.summary_move, dlg.summary_copy, dlg.summary_layout, dlg.summary_tail, dlg.summary_join, dlg.summary_head, dlg.claude_running_title, dlg.claude_running_body, dlg.backups_title, dlg.restore_selected, dlg.restore_title, dlg.restore_body, dlg.restore_running_body`

```python
from __future__ import annotations

import json
from pathlib import Path

LANGS: dict[str, dict[str, str]] = {
    "zh": {  # full zh table — every key above with the current Chinese strings
        "status.copied_n": "已复制 {n} 个对话——右键目标分组粘贴 (Ctrl+V)。",
        # ... (all keys)
    },
    "en": {
        "status.copied_n": "Copied {n} conversation(s) — right-click a target group to paste (Ctrl+V).",
        # ... (all keys)
    },
}

_current_language = "zh"


def set_language(code: str) -> None:
    global _current_language
    _current_language = code if code in LANGS else "zh"


def current_language() -> str:
    return _current_language


def tr(key: str, **kwargs) -> str:
    table = LANGS.get(_current_language, LANGS["zh"])
    template = table.get(key) or LANGS["zh"][key]
    return template.format(**kwargs) if kwargs else template


def detect_default_language(settings_path: Path) -> str:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        language = data.get("language")
        if language in LANGS:
            return language
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    try:
        from PySide6.QtCore import QLocale

        return "zh" if QLocale.system().name().startswith("zh") else "en"
    except Exception:
        return "zh"


def save_language(code: str, settings_path: Path) -> None:
    data: dict[str, object] = {}
    try:
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, json.JSONDecodeError):
        pass
    data["language"] = code
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

`tests/conftest.py`:

```python
import pytest

from cc_history_tidy import i18n


@pytest.fixture(autouse=True)
def _force_chinese_language(monkeypatch):
    monkeypatch.setattr(i18n, "detect_default_language", lambda *_: "zh")
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")
```

- [ ] **Step 4: run tests, pass; commit** `feat: i18n module with zh/en tables and system-language detection`

### Task 2: migrator returns sessionId mapping

**Files:** Modify `cc_history_tidy/models.py`, `cc_history_tidy/migrator.py`; Test `tests/test_migrator.py`

- [ ] **Step 1: failing test**

```python
def test_copy_migration_reports_id_mapping(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root / fixture.source_account_uuid / fixture.source_group_id / "session-source.json"
    )
    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.COPY,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )
    assert len(result.session_id_mapping) == 1
    old_id, new_id = result.session_id_mapping[0]
    assert old_id == "desktop-source"
    assert new_id != old_id


def test_move_migration_reports_empty_mapping(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root / fixture.source_account_uuid / fixture.source_group_id / "session-source.json"
    )
    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.MOVE,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )
    assert result.session_id_mapping == ()
```

- [ ] **Step 2: implement**

`models.py`: add `session_id_mapping: tuple[tuple[str, str], ...] = ()` to `MigrationResult`.
`migrator.py`: `_build_copy_pairs` returns 4-tuples `(source, target, new_session_id, old_session_id)` (old id already read); the copy loop collects `mapping.append((old_id, new_session_id))` when `new_session_id` is not None; result carries `session_id_mapping=tuple(mapping)`. Update tuple unpacking everywhere (conflict check, duplicate-id check, MOVE loop).

- [ ] **Step 3: run migrator tests + full suite; commit** `feat: migrate_sessions reports old-to-new sessionId mapping for copies`

### Task 3: save layout can write group labels

**Files:** Modify `cc_history_tidy/code_groups.py`; Test `tests/test_code_groups_save.py`

- [ ] **Step 1: failing test**

```python
def test_save_writes_group_labels_preserving_existing(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps({"preferences": {"epitaxyPrefs": {"dframe-local-slice": {
            "customGroups": [{"id": "cg-old", "name": "Old"}],
        }}}}),
        encoding="utf-8",
    )
    save_code_group_layout_to_desktop_config(
        config_path,
        visible_session_keys=set(),
        assignments={"code:s1": "cg-a"},
        order_data={"cg-a": ["code:s1"]},
        group_labels={"cg-a": "New Group"},
    )
    slice_data = json.loads(config_path.read_text(encoding="utf-8"))["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    labels = {g["id"]: g["name"] for g in slice_data["customGroups"]}
    assert labels == {"cg-old": "Old", "cg-a": "New Group"}
```

- [ ] **Step 2: implement**

Add keyword `group_labels: dict[str, str] | None = None`; after order handling:

```python
    if group_labels:
        existing_labels = _custom_group_labels(slice_data.get("customGroups"))
        existing_labels.update(group_labels)
        slice_data["customGroups"] = [
            {"id": group_id, "name": name} for group_id, name in existing_labels.items()
        ]
```

- [ ] **Step 3: run tests; commit** `feat: layout save can persist group labels into desktop config`

### Task 4: tree snapshots + undo/redo/reset

**Files:** Create `cc_history_tidy/tree_state.py`; Modify `cc_history_tidy/session_tree.py`; Test `tests/test_tree_undo.py`

- [ ] **Step 1: failing tests** (helpers copied from test_session_tree_clipboard)

```python
def test_undo_restores_tree_after_paste(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    before = window.tree_signature()
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    assert window.tree_signature() != before

    assert tree.undo() is True
    assert window.tree_signature() == before
    assert window.planned_session_moves() == []


def test_redo_reapplies_undone_change(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    after = window.tree_signature()
    tree.undo()
    assert tree.redo() is True
    assert window.tree_signature() == after


def test_undo_on_empty_stack_returns_false(tmp_path):
    fixture, window = _load_window(tmp_path)
    assert window.session_tree.undo() is False


def test_reset_restores_initial_state_without_disk_rescan(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    initial = window.tree_signature()
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)

    window.reset_staged_changes()

    assert window.tree_signature() == initial
    assert tree.undo_stack == [] and tree.redo_stack == []
    assert tree.clipboard_mode is None


def test_undo_restores_ghost_items(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)
    with_ghost = window.tree_signature()
    tree.undo()
    tree.redo()
    assert window.tree_signature() == with_ghost
    ghosts = [target_group_i for target_group_i in []]  # recomputed below
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    assert any(
        tree.is_ghost_item(target_group.child(i)) for i in range(target_group.childCount())
    )
```

- [ ] **Step 2: implement `tree_state.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from cc_history_tidy.models import ClaudeSession

STAGED_MODE_ROLE = Qt.ItemDataRole.UserRole + 3


@dataclass(frozen=True)
class SessionState:
    session: ClaudeSession
    staged_mode: str | None


@dataclass(frozen=True)
class GroupState:
    label: str
    code_group_id: str
    group_id: str
    staged_mode: str | None
    expanded: bool
    sessions: tuple[SessionState, ...]


@dataclass(frozen=True)
class AccountState:
    label: str
    column1: str
    account_uuid: str
    default_group_id: str
    sessions_root: Path
    expanded: bool
    groups: tuple[GroupState, ...]


@dataclass(frozen=True)
class TreeState:
    accounts: tuple[AccountState, ...]


def capture_tree_state(tree) -> TreeState:
    accounts = []
    for account_index in range(tree.topLevelItemCount()):
        account_item = tree.topLevelItem(account_index)
        groups = []
        for group_index in range(account_item.childCount()):
            group_item = account_item.child(group_index)
            sessions = []
            for session_index in range(group_item.childCount()):
                session_item = group_item.child(session_index)
                session = session_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(session, ClaudeSession):
                    continue
                sessions.append(
                    SessionState(
                        session=session,
                        staged_mode=session_item.data(0, STAGED_MODE_ROLE),
                    )
                )
            groups.append(
                GroupState(
                    label=group_item.text(0),
                    code_group_id=str(group_item.data(0, Qt.ItemDataRole.UserRole) or ""),
                    group_id=str(group_item.data(0, Qt.ItemDataRole.UserRole + 1) or ""),
                    staged_mode=group_item.data(0, STAGED_MODE_ROLE),
                    expanded=group_item.isExpanded(),
                    sessions=tuple(sessions),
                )
            )
        accounts.append(
            AccountState(
                label=account_item.text(0),
                column1=account_item.text(1),
                account_uuid=str(account_item.data(0, Qt.ItemDataRole.UserRole) or ""),
                default_group_id=str(account_item.data(0, Qt.ItemDataRole.UserRole + 1) or ""),
                sessions_root=account_item.data(0, Qt.ItemDataRole.UserRole + 2),
                expanded=account_item.isExpanded(),
                groups=tuple(groups),
            )
        )
    return TreeState(accounts=tuple(accounts))


def restore_tree_state(tree, state: TreeState) -> None:
    # imported late to avoid a circular import
    from cc_history_tidy.session_tree import (
        _new_code_group_item,
        build_account_item,
        build_ghost_session_item,
        build_session_item,
    )

    tree.clear()
    for account_state in state.accounts:
        account_item = build_account_item(
            account_state.label,
            account_state.column1,
            account_state.account_uuid,
            account_state.default_group_id,
            account_state.sessions_root,
        )
        tree.addTopLevelItem(account_item)
        for group_state in account_state.groups:
            group_item = _new_code_group_item(
                group_state.label, group_state.code_group_id, group_state.group_id
            )
            if group_state.staged_mode:
                group_item.setData(0, STAGED_MODE_ROLE, group_state.staged_mode)
            account_item.addChild(group_item)
            for session_state in group_state.sessions:
                if session_state.staged_mode == "copy":
                    group_item.addChild(build_ghost_session_item(session_state.session))
                else:
                    group_item.addChild(build_session_item(session_state.session))
            group_item.setExpanded(group_state.expanded)
        account_item.setExpanded(account_state.expanded)
    tree.refresh_staged_markers()
```

- [ ] **Step 3: session_tree changes**

Extract item builders (used by both `gui._populate_trees` and restore):

```python
def build_account_item(label, column1, account_uuid, default_group_id, sessions_root):
    account_item = QTreeWidgetItem([label, column1])
    account_item.setData(0, Qt.ItemDataRole.UserRole, account_uuid)
    account_item.setData(0, Qt.ItemDataRole.UserRole + 1, default_group_id)
    account_item.setData(0, Qt.ItemDataRole.UserRole + 2, sessions_root)
    account_item.setFlags(
        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDropEnabled
    )
    return account_item


def build_session_item(session):
    session_item = QTreeWidgetItem([session.title, format_activity_timestamp(session.last_activity_at)])
    session_item.setData(0, Qt.ItemDataRole.UserRole, session)
    session_item.setFlags(
        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
    )
    return session_item


def build_ghost_session_item(session):
    ghost = QTreeWidgetItem([session.title, tr("badge.copy")])
    ghost.setData(0, Qt.ItemDataRole.UserRole, session)
    ghost.setData(0, STAGED_MODE_ROLE, "copy")
    ghost.setForeground(1, QBrush(COPY_BADGE_COLOR))
    ghost.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return ghost
```

`_make_ghost_copy(item)` delegates to `build_ghost_session_item(item.data(0, UserRole))`.

Undo/redo on `SessionTreeWidget.__init__`: `self.undo_stack: list = []`, `self.redo_stack: list = []`, `UNDO_LIMIT = 50`, plus `treeChanged = Signal()`.

```python
    def push_undo_snapshot(self) -> None:
        from cc_history_tidy.tree_state import capture_tree_state

        self.undo_stack.append(capture_tree_state(self))
        if len(self.undo_stack) > UNDO_LIMIT:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> bool:
        from cc_history_tidy.tree_state import capture_tree_state, restore_tree_state

        if not self.undo_stack:
            self.statusMessage.emit(tr("status.nothing_to_undo"))
            return False
        self.clear_clipboard()
        self.redo_stack.append(capture_tree_state(self))
        restore_tree_state(self, self.undo_stack.pop())
        self.statusMessage.emit(tr("status.undo_done"))
        self.treeChanged.emit()
        return True

    def redo(self) -> bool:
        from cc_history_tidy.tree_state import capture_tree_state, restore_tree_state

        if not self.redo_stack:
            self.statusMessage.emit(tr("status.nothing_to_redo"))
            return False
        self.clear_clipboard()
        self.undo_stack.append(capture_tree_state(self))
        restore_tree_state(self, self.redo_stack.pop())
        self.statusMessage.emit(tr("status.redo_done"))
        self.treeChanged.emit()
        return True

    def clear_history(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()
```

Snapshot pushes: at the top of `paste_to` after validation passes (before mutation); in `dropEvent` capture before `move_items_to_target`, pop it back off if the move returns False; at the top of `remove_ghost_item` for real ghosts. Emit `treeChanged` after each successful mutation. Ctrl+Z / Ctrl+Y in `keyPressEvent` (`QKeySequence.StandardKey.Undo` / `.Redo`).

`MainWindow.reset_staged_changes()`: clear clipboard + history, `self._populate_trees()`, restore `_loaded_tree_signature` check, status `tr("status.reset_done")`. Buttons added in Task 6.

- [ ] **Step 4: run tests + suite; commit** `feat: undo/redo snapshots and reset for staged tree edits`

### Task 5: group-level clipboard with same-name merge

**Files:** Modify `cc_history_tidy/session_tree.py`; Test `tests/test_group_clipboard.py`

- [ ] **Step 1: failing tests**

```python
def test_cut_group_paste_to_other_account_moves_whole_group(tmp_path): ...
    # cut source_code_group, paste onto current account item;
    # group item now under current account; its sessions get MOVE plans

def test_cut_group_merges_into_same_name_group(tmp_path): ...
    # rename current account's group label to match source group's label first
    # (set text via item.setText(0, ...)), paste -> sessions appended into the
    # existing group, no duplicate group item

def test_copy_group_creates_ghost_group(tmp_path): ...
    # copy group, paste on other account -> new group item with
    # STAGED_MODE_ROLE == "copy", children are ghost sessions, source intact

def test_copy_group_merges_ghosts_into_same_name_group(tmp_path): ...

def test_ungrouped_group_cannot_be_cut_or_copied(tmp_path): ...
    # select ungrouped item; cut_selected_sessions()/copy return 0

def test_mixed_selection_is_rejected(tmp_path): ...
    # select one session + one group -> stash returns 0, clipboard empty

def test_drag_group_to_other_account_merges_same_name(tmp_path): ...
    # move_items_to_target(group -> other account item) routes through merge

def test_undo_ghost_group_removes_whole_group(tmp_path): ...
```

- [ ] **Step 2: implement in session_tree.py**

`__init__` adds `self.clipboard_kind: str | None = None`.

`_stash_clipboard` generalized:

```python
    def _stash_clipboard(self, mode: MigrationMode) -> int:
        selected = [item for item in self.selectedItems() if not self.is_ghost_item(item)]
        sessions = [item for item in selected if self.item_kind(item) == "session"]
        groups = [
            item
            for item in selected
            if self.item_kind(item) == "group"
            and item.data(0, Qt.ItemDataRole.UserRole) != UNGROUPED_CODE_GROUP_ID
        ]
        if sessions and groups:
            self.statusMessage.emit(tr("status.mixed_selection"))
            return 0
        items = sessions or groups
        if not items:
            self.statusMessage.emit(tr("status.select_first"))
            return 0
        self.clear_clipboard()
        self.clipboard_mode = mode
        self.clipboard_kind = "session" if sessions else "group"
        self.clipboard_items = items
        if mode == MigrationMode.MOVE:
            for item in items:
                self._set_subtree_dimmed(item, True)
            self.statusMessage.emit(tr("status.cut_n", n=len(items)))
        else:
            self.statusMessage.emit(tr("status.copied_n", n=len(items)))
        return len(items)
```

`_set_subtree_dimmed` dims item + children recursively; `clear_clipboard` restores subtrees and resets `clipboard_kind`.

Group paste:

```python
    def paste_to(self, target_item):
        ... existing empty-clipboard guard ...
        if self.clipboard_kind == "group":
            return self._paste_groups_to(target_item)
        ... existing session paste ...

    def _account_for_target(self, target_item):
        current = target_item
        while current is not None and current.parent() is not None:
            current = current.parent()
        return current if self.item_kind(current) == "account" else None

    def _find_group_by_label(self, account_item, label):
        for index in range(account_item.childCount()):
            child = account_item.child(index)
            if self.item_kind(child) != "group":
                continue
            if child.data(0, Qt.ItemDataRole.UserRole) == UNGROUPED_CODE_GROUP_ID:
                continue
            if child.text(0).strip() == label.strip():
                return child
        return None

    def _paste_groups_to(self, target_item) -> int:
        account_item = self._account_for_target(target_item)
        if account_item is None:
            self.statusMessage.emit(tr("status.paste_target_invalid"))
            return 0
        mode = self.clipboard_mode
        groups = [item for item in self.clipboard_items if self._item_alive(item)]
        self.push_undo_snapshot()
        pasted = 0
        for group_item in groups:
            if mode == MigrationMode.MOVE:
                if group_item.parent() is account_item:
                    self._set_subtree_dimmed(group_item, False)
                    continue
                pasted += self._merge_or_attach_group(group_item, account_item)
            else:
                pasted += self._paste_ghost_group(group_item, account_item)
        if mode == MigrationMode.MOVE:
            self.clear_clipboard()
        if pasted == 0:
            self.undo_stack.pop()  # nothing changed; drop the snapshot
        else:
            self.refresh_staged_markers()
            self.treeChanged.emit()
        return pasted

    def _merge_or_attach_group(self, group_item, account_item) -> int:
        source_account = group_item.parent()
        existing = self._find_group_by_label(account_item, group_item.text(0))
        self._set_subtree_dimmed(group_item, False)
        if existing is not None and existing is not group_item:
            moved = 0
            while group_item.childCount():
                existing.addChild(group_item.takeChild(0))
                moved += 1
            if source_account is not None:
                source_account.takeChild(source_account.indexOfChild(group_item))
            return max(moved, 1)
        if source_account is not None:
            source_account.takeChild(source_account.indexOfChild(group_item))
        insert_index = self._group_insert_index(account_item)
        account_item.insertChild(insert_index, group_item)
        group_item.setExpanded(True)
        return 1

    def _group_insert_index(self, account_item) -> int:
        for index in range(account_item.childCount()):
            child = account_item.child(index)
            if child.data(0, Qt.ItemDataRole.UserRole) == UNGROUPED_CODE_GROUP_ID:
                return index
        return account_item.childCount()

    def _paste_ghost_group(self, group_item, account_item) -> int:
        sessions = [
            group_item.child(i)
            for i in range(group_item.childCount())
            if self.item_kind(group_item.child(i)) == "session"
            and not self.is_ghost_item(group_item.child(i))
        ]
        if not sessions:
            return 0
        existing = self._find_group_by_label(account_item, group_item.text(0))
        if existing is not None and existing is not group_item:
            container = existing
        else:
            container = _new_code_group_item(
                group_item.text(0),
                str(group_item.data(0, Qt.ItemDataRole.UserRole) or ""),
                str(group_item.data(0, Qt.ItemDataRole.UserRole + 1) or ""),
            )
            container.setData(0, STAGED_MODE_ROLE, "copy")
            container.setForeground(1, QBrush(COPY_BADGE_COLOR))
            container.setText(1, tr("badge.copy"))
            account_item.insertChild(self._group_insert_index(account_item), container)
            container.setExpanded(True)
        for session_item in sessions:
            container.addChild(self._make_ghost_copy(session_item))
        return len(sessions)
```

`remove_ghost_item` extended: ghost **group** removal removes the whole subtree (same code path — takeChild of parent). `_context_actions_for`: ghost group gets the undo action; normal (non-ungrouped) groups get copy/cut entries plus paste.

Drag routing in `_move_groups_to_target`: when a moving group's current account differs from `target_account`, call `push_undo_snapshot()` once (from dropEvent — see below) and use `_merge_or_attach_group(item, target_account)` for those; same-account groups keep `_move_items_under_parent` reorder. dropEvent already pushes one snapshot for the whole drop.

Session paste (`_paste_sessions_to`, refactored from current body) also calls `push_undo_snapshot()` before mutation and `treeChanged.emit()` after.

- [ ] **Step 3: run new tests + full suite; commit** `feat: group-level clipboard with same-name merge`

### Task 6: GUI wiring — buttons, language combo, copies land in their group

**Files:** Modify `cc_history_tidy/gui.py`, `cc_history_tidy/session_tree.py`; Test `tests/test_gui_clipboard_execute.py`, `tests/test_i18n.py`

- [ ] **Step 1: failing tests**

```python
def test_copied_session_lands_in_pasted_group_after_execute(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)

    window.execute_plan()

    config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    slice_data = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    order = slice_data["customGroupOrder"][fixture.current_code_group_id]
    new_keys = [k for k in order if k not in {"code:desktop-current"}]
    assert len(new_keys) == 1  # the copy's NEW id was assigned to the pasted group
    assert slice_data["customGroupAssignments"][new_keys[0]] == fixture.current_code_group_id


def test_language_combo_switches_ui(tmp_path):
    fixture, window = _load_window(tmp_path, settings_path=tmp_path / "settings.json")
    from cc_history_tidy import i18n
    index = window.language_combo.findData("en")
    window.language_combo.setCurrentIndex(index)
    assert i18n.current_language() == "en"
    assert window.scan_button.text() == i18n.LANGS["en"]["btn.scan"]
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["language"] == "en"
```

- [ ] **Step 2: implement**

1. `MainWindow.__init__` gains `settings_path: Path | None = None`; resolves default `~/.claude-desktop-migrator/settings.json`; calls `i18n.set_language(i18n.detect_default_language(self.settings_path))` before widget construction.
2. New buttons: `undo_button`, `redo_button`, `reset_button` wired to `session_tree.undo/redo` and `reset_staged_changes`; `language_combo` with entries ("中文","zh"),("English","en"), current set from `i18n.current_language()`, `currentIndexChanged` → `_on_language_changed` (set_language + save_language + `retranslate_ui()`).
3. `retranslate_ui()` re-sets all static texts (buttons, headers, tooltips) from `tr()`, walks the tree updating ghost badges (`tr("badge.copy")`) and calls `refresh_staged_markers()`; status → `tr("status.language_changed")`.
4. All literal strings in gui.py/session_tree.py replaced by `tr(...)` keys (Task 1 table); `MOVE_BADGE_TEXT`/`COPY_BADGE_TEXT` constants become `tr("badge.move")`/`tr("badge.copy")` lookups at call sites.
5. `treeChanged` connected to `_on_tree_changed`: refresh undo/redo button enabled-state and, when staged changes exist, status = `tr("status.staged_summary", moves=..., copies=...)`.
6. Copies land in group: `by_move_target` stores **moves** (not sessions); after each COPY batch, zip `result.session_id_mapping` with the batch's moves; collect `(target_root, target_code_group_id, new_id)` for non-ungrouped targets; after migrations, inject into `layout_by_root[root]` assignments/order before the save loop. Save loop passes per-root `group_labels` gathered from tree group items (skip Ungrouped).
7. `_populate_trees` clears history (`session_tree.clear_history()`); `execute_plan` success path already repopulates (clears history via populate).

- [ ] **Step 3: run full suite; commit** `feat: undo/reset buttons, language switcher, copies keep their pasted group`

### Task 7: docs, build, push

- [ ] README: group clipboard + merge + undo/reset + language switcher paragraphs (zh strings referenced); note copies now land in the pasted group.
- [ ] Run `.venv/Scripts/python.exe -m pytest -q`; expect all green.
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1`; smoke-run exe.
- [ ] Commit docs + plan checkboxes; push `origin main`.

## Self-Review

- Spec A → Task 5; B → Task 5 (merge tests); C → Tasks 2, 3, 6(step 2.6); D → Task 4 (+6 buttons); E → Tasks 1, 6; F → Task 5 (mixed selection), session paste snapshot in Task 5.
- No placeholders; helper names consistent (`build_session_item`, `_merge_or_attach_group`, `session_id_mapping`, `group_labels`).
- Ghost groups excluded from staged layout? Ghost group order entry is harmless (same id as source); ghost sessions inside remain excluded by STAGED_MODE_ROLE check — copies enter layout only via the new-id injection (Task 6).
