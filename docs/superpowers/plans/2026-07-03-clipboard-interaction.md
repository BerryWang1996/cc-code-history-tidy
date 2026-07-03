# Clipboard Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Copy/Move dropdown with Explorer-style clipboard semantics (right-click copy/cut/paste, Ctrl+C/X/V, drag = move); everything stays simulated in the tree until Execute confirms and writes.

**Architecture:** `SessionTreeWidget` moves into its own module and gains a clipboard state machine (copy/cut/paste/Esc), ghost-copy items, and staged-change badges. `MainWindow` loses the mode combo; each `PlannedSessionMove` carries its own `MigrationMode`, `execute_plan` batches by mode (COPY before MOVE) and asks for confirmation before writing. migrator/backup/code_groups/paths are untouched.

**Tech Stack:** Python 3.11, PySide6, pytest (existing suite: 63 tests green).

**Spec:** `docs/superpowers/specs/2026-07-03-clipboard-interaction-design.md`

---

## File Structure

- Create `cc_history_tidy/session_tree.py` — SessionTreeWidget (drag logic moved from gui.py) + clipboard state machine + ghost copies + staged markers. Constants for roles/colors/badge texts.
- Modify `cc_history_tidy/gui.py` — MainWindow only: remove mode combo, per-mode planning, confirmation dialog, status texts, re-export SessionTreeWidget for backward compat.
- Create `tests/test_session_tree_clipboard.py` — clipboard state machine + paste semantics + markers.
- Create `tests/test_gui_clipboard_execute.py` — end-to-end staged copy/cut execute, mixed modes, confirmation cancel.
- Modify `tests/test_gui_smoke.py`, `tests/test_gui_multiroot.py`, `tests/test_review_regressions.py` — drop mode_combo usage, inject `execute_confirmer`.
- Modify `README.md` — describe the new interaction.

### Task 1: Extract SessionTreeWidget into session_tree.py (pure refactor)

**Files:**
- Create: `cc_history_tidy/session_tree.py`
- Modify: `cc_history_tidy/gui.py`

- [ ] **Step 1: Create `cc_history_tidy/session_tree.py`**

Cut the entire `SessionTreeWidget` class and the `_new_code_group_item` helper out of `gui.py` verbatim and paste into the new module with this header:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cc_history_tidy.code_groups import (
    UNGROUPED_CODE_GROUP_ID,
    UNGROUPED_CODE_GROUP_LABEL,
)
from cc_history_tidy.models import ClaudeSession
```

`_new_code_group_item` moves here as a module-level function (drop the leading underscore usage from gui: gui will import it).

- [ ] **Step 2: Update `gui.py` imports**

Remove the class and helper from gui.py; add:

```python
from cc_history_tidy.session_tree import SessionTreeWidget, _new_code_group_item
```

Keep `SessionTreeWidget` importable from `cc_history_tidy.gui` (the import above already re-exports it).

- [ ] **Step 3: Run full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 63 passed (pure refactor).

- [ ] **Step 4: Commit**

```bash
git add cc_history_tidy/session_tree.py cc_history_tidy/gui.py
git commit -m "refactor: extract SessionTreeWidget into session_tree module"
```

### Task 2: Clipboard state machine (copy/cut/clear + dimming + status signal)

**Files:**
- Modify: `cc_history_tidy/session_tree.py`
- Test: `tests/test_session_tree_clipboard.py`

- [ ] **Step 1: Write failing tests**

```python
import json

from PySide6.QtCore import Qt

from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.models import MigrationMode
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def _load_window(tmp_path, **kwargs):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        **kwargs,
    )
    window.load_environment(env)
    return fixture, window


def _find_item_by_data(root, value):
    for index in range(root.topLevelItemCount()):
        found = _find_child_by_data(root.topLevelItem(index), value)
        if found is not None:
            return found
    raise AssertionError(f"Item with data {value!r} not found")


def _find_child_by_data(item, value):
    if item.data(0, 256) == value:
        return item
    for index in range(item.childCount()):
        found = _find_child_by_data(item.child(index), value)
        if found is not None:
            return found
    return None


def test_cut_dims_items_and_escape_restores(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = group.child(0)
    tree.setCurrentItem(session_item)

    assert tree.cut_selected_sessions() == 1
    assert tree.clipboard_mode == MigrationMode.MOVE
    assert session_item.foreground(0).color().name() != "#000000"

    tree.clear_clipboard()
    assert tree.clipboard_mode is None
    assert tree.clipboard_items == []


def test_copy_sets_clipboard_without_dimming(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = group.child(0)
    tree.setCurrentItem(session_item)

    assert tree.copy_selected_sessions() == 1
    assert tree.clipboard_mode == MigrationMode.COPY


def test_new_copy_overwrites_old_cut(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_group = _find_item_by_data(tree, fixture.current_code_group_id)
    cut_item = source_group.child(0)
    tree.setCurrentItem(cut_item)
    tree.cut_selected_sessions()

    tree.setCurrentItem(current_group.child(0))
    tree.copy_selected_sessions()

    assert tree.clipboard_mode == MigrationMode.COPY
    # old cut item restored (default brush has no explicit color role set)
    assert cut_item not in tree.clipboard_items
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_tree_clipboard.py -v`
Expected: FAIL — `cut_selected_sessions` not defined.

- [ ] **Step 3: Implement clipboard state on SessionTreeWidget**

Add to `session_tree.py`:

```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor

from cc_history_tidy.models import ClaudeSession, MigrationMode

STAGED_MODE_ROLE = Qt.ItemDataRole.UserRole + 3

CUT_DIM_COLOR = QColor(150, 150, 150)
MOVE_BADGE_COLOR = QColor(30, 100, 200)
COPY_BADGE_COLOR = QColor(30, 140, 60)
MOVE_BADGE_TEXT = "待移入"
COPY_BADGE_TEXT = "⊕ 待复制"
```

```python
class SessionTreeWidget(QTreeWidget):
    statusMessage = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.clipboard_mode: MigrationMode | None = None
        self.clipboard_items: list[QTreeWidgetItem] = []

    def copy_selected_sessions(self) -> int:
        return self._stash_clipboard(MigrationMode.COPY)

    def cut_selected_sessions(self) -> int:
        return self._stash_clipboard(MigrationMode.MOVE)

    def _stash_clipboard(self, mode: MigrationMode) -> int:
        items = [
            item
            for item in self.selectedItems()
            if self.item_kind(item) == "session" and not self.is_ghost_item(item)
        ]
        if not items:
            self.statusMessage.emit("先选中要复制/剪切的对话。")
            return 0
        self.clear_clipboard()
        self.clipboard_mode = mode
        self.clipboard_items = items
        if mode == MigrationMode.MOVE:
            for item in items:
                self._set_item_dimmed(item, True)
            self.statusMessage.emit(
                f"已剪切 {len(items)} 个对话——右键目标分组粘贴 (Ctrl+V)。"
            )
        else:
            self.statusMessage.emit(
                f"已复制 {len(items)} 个对话——右键目标分组粘贴 (Ctrl+V)。"
            )
        return len(items)

    def clear_clipboard(self) -> None:
        for item in self.clipboard_items:
            try:
                self._set_item_dimmed(item, False)
            except RuntimeError:
                pass  # item was deleted with a tree rebuild
        self.clipboard_items = []
        self.clipboard_mode = None

    def is_ghost_item(self, item: QTreeWidgetItem) -> bool:
        return item.data(0, STAGED_MODE_ROLE) == "copy"

    @staticmethod
    def _set_item_dimmed(item: QTreeWidgetItem, dimmed: bool) -> None:
        brush = QBrush(CUT_DIM_COLOR) if dimmed else QBrush()
        item.setForeground(0, brush)
        item.setForeground(1, brush)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_tree_clipboard.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cc_history_tidy/session_tree.py tests/test_session_tree_clipboard.py
git commit -m "feat: clipboard state machine with cut dimming on session tree"
```

### Task 3: paste_to with ghost copies and staged markers

**Files:**
- Modify: `cc_history_tidy/session_tree.py`
- Test: `tests/test_session_tree_clipboard.py`

- [ ] **Step 1: Write failing tests**

```python
def test_paste_cut_into_group_moves_item(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    assert tree.paste_to(target_group) == 1
    assert session_item.parent() is target_group
    assert tree.clipboard_mode is None  # cut clipboard clears after paste
    # cross-account move gets the badge
    assert session_item.text(1) == "待移入"


def test_paste_copy_creates_ghost_and_allows_repeat(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.copy_selected_sessions()

    assert tree.paste_to(target_group) == 1
    assert tree.paste_to(target_group) == 1  # copy clipboard survives
    ghosts = [
        target_group.child(i)
        for i in range(target_group.childCount())
        if tree.is_ghost_item(target_group.child(i))
    ]
    assert len(ghosts) == 2
    assert all(g.text(1) == "⊕ 待复制" for g in ghosts)
    # source stays put
    assert session_item.parent() is source_group


def test_paste_to_account_lands_in_ungrouped(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    assert tree.paste_to(current_account) == 1
    assert session_item.parent().data(0, 256) == "ungrouped"


def test_paste_to_session_inserts_after_it(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    anchor = target_group.child(0)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    tree.paste_to(anchor)

    assert target_group.indexOfChild(session_item) == target_group.indexOfChild(anchor) + 1


def test_paste_with_empty_clipboard_is_noop(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    assert tree.paste_to(target_group) == 0


def test_cut_paste_back_to_origin_is_noop(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    tree.paste_to(source_group)

    assert session_item.parent() is source_group
    assert session_item.text(1) != "待移入"
    assert window.planned_session_moves() == []
    assert window.tree_signature() == window._loaded_tree_signature


def test_remove_ghost_item_undoes_staged_copy(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)
    ghost = next(
        target_group.child(i)
        for i in range(target_group.childCount())
        if tree.is_ghost_item(target_group.child(i))
    )

    tree.remove_ghost_item(ghost)

    assert all(
        not tree.is_ghost_item(target_group.child(i))
        for i in range(target_group.childCount())
    )
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_tree_clipboard.py -v`
Expected: new tests FAIL — `paste_to` not defined.

- [ ] **Step 3: Implement paste_to, ghosts, markers**

Add to `SessionTreeWidget`:

```python
    def paste_to(self, target_item: QTreeWidgetItem) -> int:
        if self.clipboard_mode is None or not self.clipboard_items:
            self.statusMessage.emit("剪贴板为空——先复制 (Ctrl+C) 或剪切 (Ctrl+X)。")
            return 0
        placement = self._paste_placement(target_item)
        if placement is None:
            self.statusMessage.emit("只能粘贴到分组、账户或对话上。")
            return 0
        group_item, insert_index = placement
        mode = self.clipboard_mode
        items = [item for item in self.clipboard_items if self._item_alive(item)]
        pasted = 0
        for item in items:
            if mode == MigrationMode.MOVE:
                parent = item.parent()
                if parent is None:
                    continue
                old_index = parent.indexOfChild(item)
                if parent is group_item and old_index < insert_index:
                    insert_index -= 1
                parent.takeChild(old_index)
                group_item.insertChild(insert_index, item)
                self._set_item_dimmed(item, False)
            else:
                group_item.insertChild(insert_index, self._make_ghost_copy(item))
            insert_index += 1
            pasted += 1
        if mode == MigrationMode.MOVE:
            self.clear_clipboard()
        self.refresh_staged_markers()
        return pasted

    def _paste_placement(self, target_item: QTreeWidgetItem | None):
        if target_item is None:
            return None
        kind = self.item_kind(target_item)
        if kind == "group":
            return target_item, target_item.childCount()
        if kind == "account":
            group = self._ungrouped_group_for_account(target_item)
            return group, group.childCount()
        if kind == "session":
            group = target_item.parent()
            if group is None:
                return None
            return group, group.indexOfChild(target_item) + 1
        return None

    def _item_alive(self, item: QTreeWidgetItem) -> bool:
        try:
            return item.treeWidget() is self
        except RuntimeError:
            return False

    def _make_ghost_copy(self, item: QTreeWidgetItem) -> QTreeWidgetItem:
        session = item.data(0, Qt.ItemDataRole.UserRole)
        ghost = QTreeWidgetItem([item.text(0), COPY_BADGE_TEXT])
        ghost.setData(0, Qt.ItemDataRole.UserRole, session)
        ghost.setData(0, STAGED_MODE_ROLE, "copy")
        ghost.setForeground(1, QBrush(COPY_BADGE_COLOR))
        ghost.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return ghost

    def remove_ghost_item(self, item: QTreeWidgetItem) -> None:
        if not self.is_ghost_item(item):
            return
        parent = item.parent()
        if parent is not None:
            parent.takeChild(parent.indexOfChild(item))
        self.statusMessage.emit("已撤销暂存副本。")

    def refresh_staged_markers(self) -> None:
        for account_index in range(self.topLevelItemCount()):
            account_item = self.topLevelItem(account_index)
            account_uuid = account_item.data(0, Qt.ItemDataRole.UserRole)
            sessions_root = account_item.data(0, Qt.ItemDataRole.UserRole + 2)
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                for session_index in range(group_item.childCount()):
                    session_item = group_item.child(session_index)
                    session = session_item.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(session, ClaudeSession):
                        continue
                    if self.is_ghost_item(session_item):
                        continue
                    staged_move = (
                        session.account_uuid != account_uuid
                        or session.sessions_root != sessions_root
                    )
                    if staged_move:
                        session_item.setText(1, MOVE_BADGE_TEXT)
                        session_item.setForeground(1, QBrush(MOVE_BADGE_COLOR))
                    else:
                        session_item.setText(1, str(session.last_activity_at or ""))
                        if session_item not in self.clipboard_items:
                            session_item.setForeground(1, QBrush())
```

Also call `self.refresh_staged_markers()` at the end of the successful branch in `dropEvent` (right after `self.normalize_structure()`), so drag moves get badges too.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_tree_clipboard.py -v`
Expected: all pass. Also run the full suite: `.venv/Scripts/python.exe -m pytest -q` — expect existing pass counts unchanged.

- [ ] **Step 5: Commit**

```bash
git add cc_history_tidy/session_tree.py tests/test_session_tree_clipboard.py
git commit -m "feat: paste with ghost copies and staged-change badges"
```

### Task 4: Context menu and keyboard shortcuts

**Files:**
- Modify: `cc_history_tidy/session_tree.py`
- Test: `tests/test_session_tree_clipboard.py`

- [ ] **Step 1: Write failing tests**

```python
def test_context_actions_for_session_offer_copy_cut(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    labels = [label for label, _ in tree._context_actions_for(group.child(0))]
    assert any("复制" in label for label in labels)
    assert any("剪切" in label for label in labels)
    assert not any("粘贴" in label for label in labels)  # clipboard empty


def test_context_actions_offer_paste_when_clipboard_full(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    tree.setCurrentItem(group.child(0))
    tree.copy_selected_sessions()
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    labels = [label for label, _ in tree._context_actions_for(target_group)]
    assert any("粘贴" in label for label in labels)


def test_context_actions_for_ghost_offer_undo_only(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)
    ghost = next(
        target_group.child(i)
        for i in range(target_group.childCount())
        if tree.is_ghost_item(target_group.child(i))
    )
    labels = [label for label, _ in tree._context_actions_for(ghost)]
    assert labels == ["撤销此暂存副本"]


def test_ctrl_shortcuts_drive_clipboard(tmp_path):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)

    tree.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    )
    assert tree.clipboard_mode == MigrationMode.MOVE

    tree.setCurrentItem(target_group)
    tree.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    )
    assert session_item.parent() is target_group

    tree.setCurrentItem(session_item)
    tree.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    )
    assert tree.clipboard_mode == MigrationMode.COPY

    tree.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert tree.clipboard_mode is None
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_tree_clipboard.py -v`
Expected: new tests FAIL — `_context_actions_for` missing.

- [ ] **Step 3: Implement menu + shortcuts**

Add imports `QKeyEvent`-free implementation using `QKeySequence` and `QMenu`:

```python
from PySide6.QtGui import QBrush, QColor, QKeySequence
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem
```

```python
    def _context_actions_for(self, item: QTreeWidgetItem):
        actions = []
        kind = self.item_kind(item)
        if kind == "session" and self.is_ghost_item(item):
            return [("撤销此暂存副本", lambda checked=False, it=item: self.remove_ghost_item(it))]
        if kind == "session":
            actions.append(("复制\tCtrl+C", lambda checked=False: self.copy_selected_sessions()))
            actions.append(("剪切\tCtrl+X", lambda checked=False: self.cut_selected_sessions()))
        if (
            kind in {"group", "account", "session"}
            and self.clipboard_mode is not None
            and self.clipboard_items
        ):
            actions.append(("粘贴\tCtrl+V", lambda checked=False, it=item: self.paste_to(it)))
        return actions

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt override
        item = self.itemAt(event.pos())
        if item is None:
            return
        if item not in self.selectedItems():
            self.setCurrentItem(item)
        actions = self._context_actions_for(item)
        if not actions:
            return
        menu = QMenu(self)
        for label, handler in actions:
            menu.addAction(label).triggered.connect(handler)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selected_sessions()
            return
        if event.matches(QKeySequence.StandardKey.Cut):
            self.cut_selected_sessions()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            if self.currentItem() is not None:
                self.paste_to(self.currentItem())
            return
        if event.key() == Qt.Key.Key_Escape and self.clipboard_items:
            self.clear_clipboard()
            self.statusMessage.emit("已清空剪贴板。")
            return
        super().keyPressEvent(event)
```

- [ ] **Step 4: Run tests, verify pass; commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_tree_clipboard.py -q`

```bash
git add cc_history_tidy/session_tree.py tests/test_session_tree_clipboard.py
git commit -m "feat: context menu and Ctrl+C/X/V shortcuts for session clipboard"
```

### Task 5: Per-item migration mode in planning and execute

**Files:**
- Modify: `cc_history_tidy/gui.py`
- Test: `tests/test_gui_clipboard_execute.py`

- [ ] **Step 1: Write failing tests**

```python
import json

from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.models import MigrationMode
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def _load_window(tmp_path, **kwargs):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        execute_confirmer=kwargs.pop("execute_confirmer", lambda summary: True),
        **kwargs,
    )
    window.load_environment(env)
    return fixture, window


def _find_item_by_data(root, value):
    for index in range(root.topLevelItemCount()):
        found = _find_child_by_data(root.topLevelItem(index), value)
        if found is not None:
            return found
    raise AssertionError(f"Item with data {value!r} not found")


def _find_child_by_data(item, value):
    if item.data(0, 256) == value:
        return item
    for index in range(item.childCount()):
        found = _find_child_by_data(item.child(index), value)
        if found is not None:
            return found
    return None


def test_cut_paste_plans_move_and_copy_paste_plans_copy(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)

    current_ungrouped_session = _find_item_by_data(tree, "ungrouped").child(0)
    tree.setCurrentItem(current_ungrouped_session)
    # copy a current-account session into the SOURCE account
    tree.copy_selected_sessions()
    source_account = _find_item_by_data(tree, fixture.source_account_uuid)
    tree.paste_to(source_account)

    planned = window.planned_session_moves()
    modes = sorted(move.mode.value for move in planned)
    assert modes == ["copy", "move"]


def test_execute_mixed_copy_and_move(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    # MOVE session-source into the current account
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    # COPY session-current into the source account
    current_session_item = _find_item_by_data(tree, fixture.current_code_group_id).child(0)
    tree.setCurrentItem(current_session_item)
    tree.copy_selected_sessions()
    tree.paste_to(_find_item_by_data(tree, fixture.source_account_uuid))

    window.execute_plan()

    moved_target = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    )
    assert moved_target.exists()
    assert not (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    ).exists()
    # the copy landed in the source account with a fresh session id
    source_account_dir = fixture.sessions_root / fixture.source_account_uuid
    copied_ids = {
        json.loads(p.read_text(encoding="utf-8"))["sessionId"]
        for p in source_account_dir.rglob("*.json")
    }
    assert "desktop-current" not in copied_ids
    assert len(copied_ids) == 1


def test_execute_confirmer_cancel_leaves_disk_untouched(tmp_path):
    fixture, window = _load_window(tmp_path, execute_confirmer=lambda summary: False)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )

    window.execute_plan()

    assert source_file.exists()
    assert not (tmp_path / "backups").exists()
    assert "取消" in window.status_label.text()


def test_ghost_copy_does_not_pollute_staged_layout(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)

    visible_keys, by_root = window.staged_code_group_layout_by_root()
    assignments, _order = by_root[fixture.sessions_root]
    # the original keeps its group; the ghost adds nothing
    assert assignments["code:desktop-source"] == fixture.source_code_group_id

    window.execute_plan()

    config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    slice_data = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    assert slice_data["customGroupAssignments"]["code:desktop-source"] == fixture.source_code_group_id
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_clipboard_execute.py -v`
Expected: FAIL — `execute_confirmer` unknown kwarg, `PlannedSessionMove` has no `mode`.

- [ ] **Step 3: Implement in gui.py**

3a. `PlannedSessionMove` gains a mode field:

```python
@dataclass(frozen=True)
class PlannedSessionMove:
    session: ClaudeSession
    source_sessions_root: Path
    target_sessions_root: Path
    target_account_uuid: str
    target_group_id: str
    target_code_group_id: str
    mode: MigrationMode
```

3b. `MainWindow.__init__` accepts `execute_confirmer: Callable[[str], bool] | None = None`, stores it, connects `self.session_tree.statusMessage.connect(self.status_label.setText)`. Remove the `mode_combo` widget, its `addItem` calls and `action_row.addWidget(self.mode_combo)`; delete `selected_migration_mode`.

3c. `planned_session_moves` — session loop becomes:

```python
                for session_index in range(group_item.childCount()):
                    session_item = group_item.child(session_index)
                    session = session_item.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(session, ClaudeSession):
                        continue
                    is_ghost = session_item.data(0, STAGED_MODE_ROLE) == "copy"
                    if (
                        not is_ghost
                        and session.account_uuid == account_uuid
                        and session.sessions_root == target_sessions_root
                    ):
                        continue
                    target_group_id = self._target_filesystem_group_id(account_item, group_id, session)
                    moves.append(
                        PlannedSessionMove(
                            session=session,
                            source_sessions_root=session.sessions_root,
                            target_sessions_root=target_sessions_root,
                            target_account_uuid=account_uuid,
                            target_group_id=target_group_id,
                            target_code_group_id=code_group_id,
                            mode=MigrationMode.COPY if is_ghost else MigrationMode.MOVE,
                        )
                    )
```

Import `STAGED_MODE_ROLE` from `cc_history_tidy.session_tree`.

3d. `staged_code_group_layout_by_root` — drop the `exclude_session_ids` parameter; skip ghost items instead:

```python
                for session_index in range(group_item.childCount()):
                    session_item = group_item.child(session_index)
                    session = session_item.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(session, ClaudeSession):
                        continue
                    if session_item.data(0, STAGED_MODE_ROLE) == "copy":
                        continue
```

3e. `execute_plan` — after computing `planned`/`has_tree_changes` and before backups:

```python
        move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
        copy_count = len(planned) - move_count
        if not self._confirm_execution(self._execution_summary(move_count, copy_count, has_tree_changes)):
            self.status_label.setText("已取消，未做任何更改。")
            return
        visible_keys, layout_by_root = self.staged_code_group_layout_by_root()
```

Remove the old `mode = self.selected_migration_mode()` and `excluded_session_ids` block. Batch key gains mode, and COPY batches run first (so a session that is both copied and moved in one execute is copied from its original location before the move):

```python
        by_move_target: dict[tuple[MigrationMode, Path, Path, str, str, str], list[ClaudeSession]] = {}
        for move in planned:
            key = (
                move.mode,
                move.source_sessions_root,
                move.target_sessions_root,
                move.session.account_uuid,
                move.target_account_uuid,
                move.target_group_id,
            )
            by_move_target.setdefault(key, []).append(move.session)

        ordered_batches = sorted(
            by_move_target.items(),
            key=lambda entry: 0 if entry[0][0] == MigrationMode.COPY else 1,
        )
        try:
            for (
                batch_mode,
                source_sessions_root,
                target_sessions_root,
                source_account_uuid,
                target_account_uuid,
                target_group_id,
            ), sessions in ordered_batches:
                result = migrate_sessions(
                    sessions_root=source_sessions_root,
                    source_account_uuid=source_account_uuid,
                    target_account_uuid=target_account_uuid,
                    session_files=[session.metadata_path for session in sessions],
                    mode=batch_mode,
                    backup_root=self.backup_parent,
                    target_group_id=target_group_id,
                    config_path=target_sessions_root.parent / "claude_desktop_config.json",
                    target_sessions_root=target_sessions_root,
                    reuse_backup=backups[source_sessions_root],
                )
```

3f. Confirmation helpers on MainWindow:

```python
    def _confirm_execution(self, summary: str) -> bool:
        if self.execute_confirmer is not None:
            return self.execute_confirmer(summary)
        answer = QMessageBox.question(self, "确认执行", summary)
        return answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def _execution_summary(move_count: int, copy_count: int, layout_changed: bool) -> str:
        parts = []
        if move_count:
            parts.append(f"移动 {move_count} 个对话")
        if copy_count:
            parts.append(f"创建 {copy_count} 个副本")
        if layout_changed:
            parts.append("更新分组布局")
        return "将" + "、".join(parts) + "。执行前会自动备份所有涉及的目录。继续？"
```

3g. `_populate_trees` starts with `self.session_tree.clear_clipboard()` before `self.session_tree.clear()` (rescan discards clipboard). `show_dry_run` becomes:

```python
    def show_dry_run(self) -> None:
        self.refresh_execute_state()
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
        copy_count = len(planned) - move_count
        layout_status = "yes" if has_tree_changes else "no"
        self.status_label.setText(
            f"Dry-run: {move_count} 个移动, {copy_count} 个复制; 布局更新: {layout_status}."
        )
```

- [ ] **Step 4: Run new tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_clipboard_execute.py -v`
Expected: 4 passed. Full suite will still fail on legacy mode_combo references — fixed in Task 6.

- [ ] **Step 5: Commit**

```bash
git add cc_history_tidy/gui.py tests/test_gui_clipboard_execute.py
git commit -m "feat: per-item migration mode with execute confirmation, drop mode combo"
```

### Task 6: Adapt legacy tests

**Files:**
- Modify: `tests/test_gui_smoke.py`, `tests/test_gui_multiroot.py`, `tests/test_review_regressions.py`

- [ ] **Step 1: Update tests**

- Every `MainWindow(...)` that calls `execute_plan` gains `execute_confirmer=lambda summary: True`.
- Delete all `window.mode_combo.setCurrentText("Move")` lines (tree move is MOVE now).
- `test_main_window_defaults_to_copy_mode_for_cross_account_migration` (test_gui_smoke.py): rename to `test_copy_paste_keeps_source_and_creates_copy`, drive it via clipboard:

```python
def test_copy_paste_keeps_source_and_creates_copy(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        execute_confirmer=lambda summary: True,
    )
    window.load_environment(env)
    source_group = _find_item_by_data(window.session_tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    window.session_tree.setCurrentItem(source_group.child(0))
    window.session_tree.copy_selected_sessions()
    window.session_tree.paste_to(target_group)

    window.execute_plan()

    assert (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    ).exists()
    target_dir = fixture.sessions_root / fixture.current_account_uuid / fixture.current_group_id
    copied_ids = {
        json.loads(p.read_text(encoding="utf-8"))["sessionId"] for p in target_dir.glob("*.json")
    }
    assert "desktop-source" not in copied_ids
    assert len(copied_ids - {"desktop-current", "desktop-ungrouped"}) == 1
```

- `test_dry_run_reports_layout_only_changes`: assertions become

```python
    assert "0 个移动, 0 个复制" in window.status_label.text()
    assert "布局更新: yes" in window.status_label.text()
```

- `test_review_regressions.py::test_copy_execute_keeps_original_grouping_and_writes_no_stale_target_entry`: replace the `mode_combo` + take/add staging with clipboard copy/paste (`copy_selected_sessions()` on the source session, `paste_to(target_group)`); assertions stay identical.

- [ ] **Step 2: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (63 legacy-adapted + ~15 new).

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: adapt suite to clipboard interaction model"
```

### Task 7: Docs, build, push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite the interaction section of README**

Replace the "The UI is a single editable tree…" paragraph block with:

```markdown
The UI is a single editable tree that behaves like a file manager. Everything
is simulated until `Execute`:

- Right-click a conversation (multi-select supported): `复制 (Ctrl+C)` /
  `剪切 (Ctrl+X)`; right-click a target group/account/conversation:
  `粘贴 (Ctrl+V)`. `Esc` clears the clipboard.
- Cut conversations are dimmed until pasted. Pasted copies appear as green
  `⊕ 待复制` ghost entries (right-click to undo one); conversations staged to
  move into another account show a blue `待移入` badge.
- Dragging = move. Dragging inside one account only regroups (layout change,
  no file moves); dragging/pasting into another account or install root moves
  the metadata file at Execute time.
- Copies are written with a fresh `sessionId` and start out ungrouped; the
  original keeps its place and grouping.
- `Execute` shows a summary ("移动 N 个对话、创建 M 个副本、更新分组布局")
  and only writes after confirmation, with full per-root backups. Re-`Scan`
  discards all staged edits.
```

Also remove the (now wrong) sentence in Safety Model saying "Copy mode keeps the source metadata…" — replace "Copy mode" wording with "Pasting a copy". Keep the rest.

- [ ] **Step 2: Full suite + build + push**

```bash
.venv/Scripts/python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1
git add README.md docs/superpowers/plans/2026-07-03-clipboard-interaction.md
git commit -m "docs: describe clipboard interaction model"
git push origin main
```

Expected: tests pass, `dist/cc-code-history-tidy.exe` rebuilt, push accepted.

---

## Self-Review

- **Spec coverage:** interaction table → Tasks 2-4; paste-target semantics → Task 3; clipboard rules (overwrite, cut-once, Esc, no-op paste-back) → Tasks 2-3; ghost copies + undo → Task 3-4; badges incl. no-badge-for-regroup → Task 3 (`refresh_staged_markers` only badges cross-account/root); per-mode execute + COPY-before-MOVE ordering + confirm dialog + dry-run summary + mode-combo removal → Task 5; rescan discards staging/clipboard → Task 5 step 3g; tests → Tasks 2-6; docs → Task 7.
- **Placeholder scan:** none — all steps carry code or exact commands.
- **Type consistency:** `STAGED_MODE_ROLE` defined in session_tree.py, imported by gui.py (Task 5 step 3c); `PlannedSessionMove.mode: MigrationMode` used in Tasks 5-6; `execute_confirmer: Callable[[str], bool] | None` matches test usage.
