from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from cc_history_tidy.code_groups import (
    UNGROUPED_CODE_GROUP_ID,
    UNGROUPED_CODE_GROUP_LABEL,
)
from cc_history_tidy.i18n import tr
from cc_history_tidy.models import ClaudeSession, MigrationMode

STAGED_MODE_ROLE = Qt.ItemDataRole.UserRole + 3
UNDO_LIMIT = 50

CUT_DIM_COLOR = QColor(150, 150, 150)
MOVE_BADGE_COLOR = QColor(30, 100, 200)
COPY_BADGE_COLOR = QColor(30, 140, 60)
MOVE_BADGE_TEXT = "待移入"
COPY_BADGE_TEXT = "⊕ 待复制"


def format_activity_timestamp(epoch_ms: int | None) -> str:
    if not epoch_ms:
        return ""
    try:
        return datetime.fromtimestamp(epoch_ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return str(epoch_ms)


class SessionTreeWidget(QTreeWidget):
    statusMessage = Signal(str)
    treeChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.clipboard_mode: MigrationMode | None = None
        self.clipboard_kind: str | None = None
        self.clipboard_items: list[QTreeWidgetItem] = []
        self.undo_stack: list = []
        self.redo_stack: list = []

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

    def copy_selected_sessions(self) -> int:
        return self._stash_clipboard(MigrationMode.COPY)

    def cut_selected_sessions(self) -> int:
        return self._stash_clipboard(MigrationMode.MOVE)

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

    def clear_clipboard(self) -> None:
        for item in self.clipboard_items:
            try:
                self._set_subtree_dimmed(item, False)
            except RuntimeError:
                pass  # item was destroyed by a tree rebuild
        self.clipboard_items = []
        self.clipboard_mode = None
        self.clipboard_kind = None

    def _set_subtree_dimmed(self, item: QTreeWidgetItem, dimmed: bool) -> None:
        self._set_item_dimmed(item, dimmed)
        if not dimmed and self.is_ghost_item(item):
            item.setForeground(1, QBrush(COPY_BADGE_COLOR))
        for index in range(item.childCount()):
            self._set_subtree_dimmed(item.child(index), dimmed)

    def is_ghost_item(self, item: QTreeWidgetItem) -> bool:
        return item.data(0, STAGED_MODE_ROLE) == "copy"

    @staticmethod
    def _set_item_dimmed(item: QTreeWidgetItem, dimmed: bool) -> None:
        brush = QBrush(CUT_DIM_COLOR) if dimmed else QBrush()
        item.setForeground(0, brush)
        item.setForeground(1, brush)

    def paste_to(self, target_item: QTreeWidgetItem | None) -> int:
        if self.clipboard_mode is None or not self.clipboard_items:
            self.statusMessage.emit(tr("status.paste_empty"))
            return 0
        if self.clipboard_kind == "group":
            return self._paste_groups_to(target_item)
        placement = self._paste_placement(target_item)
        if placement is None:
            self.statusMessage.emit(tr("status.paste_target_invalid"))
            return 0
        group_item, insert_index = placement
        mode = self.clipboard_mode
        items = [item for item in self.clipboard_items if self._item_alive(item)]
        self.push_undo_snapshot()
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
        if pasted == 0:
            self.undo_stack.pop()
        else:
            self.refresh_staged_markers()
            self.treeChanged.emit()
        return pasted

    def _paste_groups_to(self, target_item: QTreeWidgetItem | None) -> int:
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
                    # pasted back into its own account: nothing to move
                    self._set_subtree_dimmed(group_item, False)
                    continue
                pasted += self._merge_or_attach_group(group_item, account_item)
            else:
                pasted += self._paste_ghost_group(group_item, account_item)
        if mode == MigrationMode.MOVE:
            self.clear_clipboard()
        if pasted == 0:
            self.undo_stack.pop()
        else:
            self.refresh_staged_markers()
            self.treeChanged.emit()
        return pasted

    def _account_for_target(self, target_item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
        current = target_item
        while current is not None and current.parent() is not None:
            current = current.parent()
        if current is not None and self.item_kind(current) == "account":
            return current
        return None

    def _find_group_by_label(
        self, account_item: QTreeWidgetItem, label: str
    ) -> QTreeWidgetItem | None:
        for index in range(account_item.childCount()):
            child = account_item.child(index)
            if self.item_kind(child) != "group":
                continue
            if child.data(0, Qt.ItemDataRole.UserRole) == UNGROUPED_CODE_GROUP_ID:
                continue
            if child.text(0).strip() == label.strip():
                return child
        return None

    def _group_insert_index(self, account_item: QTreeWidgetItem) -> int:
        for index in range(account_item.childCount()):
            child = account_item.child(index)
            if child.data(0, Qt.ItemDataRole.UserRole) == UNGROUPED_CODE_GROUP_ID:
                return index
        return account_item.childCount()

    def _merge_or_attach_group(
        self, group_item: QTreeWidgetItem, account_item: QTreeWidgetItem
    ) -> int:
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
        account_item.insertChild(self._group_insert_index(account_item), group_item)
        group_item.setExpanded(True)
        return 1

    def _paste_ghost_group(
        self, group_item: QTreeWidgetItem, account_item: QTreeWidgetItem
    ) -> int:
        sessions = [
            group_item.child(index)
            for index in range(group_item.childCount())
            if self.item_kind(group_item.child(index)) == "session"
            and not self.is_ghost_item(group_item.child(index))
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
            build_ghost_group_marker(container, "copy")
            account_item.insertChild(self._group_insert_index(account_item), container)
            container.setExpanded(True)
        for session_item in sessions:
            container.addChild(self._make_ghost_copy(session_item))
        return len(sessions)

    def _paste_placement(
        self, target_item: QTreeWidgetItem | None
    ) -> tuple[QTreeWidgetItem, int] | None:
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
        return build_ghost_session_item(item.data(0, Qt.ItemDataRole.UserRole))

    def remove_ghost_item(self, item: QTreeWidgetItem) -> None:
        if not self.is_ghost_item(item):
            return
        parent = item.parent()
        if parent is None:
            return
        self.push_undo_snapshot()
        parent.takeChild(parent.indexOfChild(item))
        self.statusMessage.emit(tr("status.ghost_removed"))
        self.treeChanged.emit()

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
                        session_item.setText(1, format_activity_timestamp(session.last_activity_at))
                        if session_item not in self.clipboard_items:
                            session_item.setForeground(1, QBrush())

    def _context_actions_for(self, item: QTreeWidgetItem):
        kind = self.item_kind(item)
        if self.is_ghost_item(item):
            return [(tr("menu.undo_ghost"), lambda checked=False, it=item: self.remove_ghost_item(it))]
        actions = []
        copyable = kind == "session" or (
            kind == "group"
            and item.data(0, Qt.ItemDataRole.UserRole) != UNGROUPED_CODE_GROUP_ID
        )
        if copyable:
            actions.append((tr("menu.copy"), lambda checked=False: self.copy_selected_sessions()))
            actions.append((tr("menu.cut"), lambda checked=False: self.cut_selected_sessions()))
        if (
            kind in {"group", "account", "session"}
            and self.clipboard_mode is not None
            and self.clipboard_items
        ):
            actions.append((tr("menu.paste"), lambda checked=False, it=item: self.paste_to(it)))
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
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
            return
        if event.key() == Qt.Key.Key_Escape and self.clipboard_items:
            self.clear_clipboard()
            self.statusMessage.emit(tr("status.clipboard_cleared"))
            return
        super().keyPressEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        moving_items = self._selected_movable_items()
        target_item = self._drop_target_item(event)
        if moving_items and target_item is not None:
            self.push_undo_snapshot()
            if self.move_items_to_target(
                moving_items,
                target_item,
                self.dropIndicatorPosition(),
            ):
                self.normalize_structure()
                self.refresh_staged_markers()
                self.treeChanged.emit()
                event.acceptProposedAction()
                return
            self.undo_stack.pop()
        event.ignore()

    def move_items_to_target(self, moving_items: list[QTreeWidgetItem], target_item: QTreeWidgetItem, position) -> bool:
        moving_kinds = {self.item_kind(item) for item in moving_items}
        if moving_kinds == {"group"}:
            return self._move_groups_to_target(moving_items, target_item, position)
        if moving_kinds == {"session"}:
            return self._move_sessions_to_target(moving_items, target_item, position)
        return False

    def normalize_structure(self) -> None:
        while self._normalize_once():
            pass

    def item_kind(self, item: QTreeWidgetItem | None) -> str:
        if item is None:
            return "none"
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(payload, ClaudeSession):
            return "session"
        if isinstance(payload, str) and item.parent() is None:
            return "account"
        if isinstance(payload, str) and isinstance(item.data(0, Qt.ItemDataRole.UserRole + 1), str):
            return "group"
        return "unknown"

    def _selected_movable_items(self) -> list[QTreeWidgetItem]:
        selected = [
            item
            for item in self.selectedItems()
            if self.item_kind(item) in {"group", "session"}
        ]
        return sorted(selected, key=self._visual_path)

    def _drop_target_item(self, event) -> QTreeWidgetItem | None:
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        return self.itemAt(position)

    def _move_groups_to_target(self, moving_items: list[QTreeWidgetItem], target_item: QTreeWidgetItem, position) -> bool:
        target_kind = self.item_kind(target_item)
        if target_kind == "account":
            target_account = target_item
            insert_index = target_account.childCount()
        elif target_kind == "group":
            target_account = target_item.parent()
            if target_account is None:
                return False
            target_index = target_account.indexOfChild(target_item)
            insert_index = target_index if self._is_above_drop(position) else target_index + 1
        elif target_kind == "session":
            target_group = target_item.parent()
            target_account = target_group.parent() if target_group is not None else None
            if target_account is None:
                return False
            target_index = target_account.indexOfChild(target_group)
            insert_index = target_index if self._is_above_drop(position) else target_index + 1
        else:
            return False
        # Groups dragged into a DIFFERENT account are a migration (cut+paste):
        # they merge into a same-name group when one exists. Same-account
        # drags stay pure reorders.
        cross_account = [item for item in moving_items if item.parent() is not target_account]
        same_account = [item for item in moving_items if item.parent() is target_account]
        handled = False
        for item in cross_account:
            if self._merge_or_attach_group(item, target_account):
                handled = True
        if same_account:
            handled = self._move_items_under_parent(same_account, target_account, insert_index) or handled
        return handled

    def _move_sessions_to_target(self, moving_items: list[QTreeWidgetItem], target_item: QTreeWidgetItem, position) -> bool:
        target_kind = self.item_kind(target_item)
        if target_kind == "group":
            target_group = target_item
            insert_index = target_group.childCount()
        elif target_kind == "account":
            target_group = self._ungrouped_group_for_account(target_item)
            insert_index = target_group.childCount()
        elif target_kind == "session":
            target_group = target_item.parent()
            if target_group is None:
                return False
            target_index = target_group.indexOfChild(target_item)
            insert_index = target_index if self._is_above_drop(position) else target_index + 1
        else:
            return False
        return self._move_items_under_parent(moving_items, target_group, insert_index)

    def _move_items_under_parent(
        self,
        moving_items: list[QTreeWidgetItem],
        target_parent: QTreeWidgetItem,
        insert_index: int,
    ) -> bool:
        if target_parent in moving_items:
            return False
        detached: list[QTreeWidgetItem] = []
        for item in moving_items:
            parent = item.parent()
            if parent is None:
                return False
            old_index = parent.indexOfChild(item)
            if parent == target_parent and old_index < insert_index:
                insert_index -= 1
            detached.append(parent.takeChild(old_index))
        for offset, item in enumerate(detached):
            target_parent.insertChild(insert_index + offset, item)
        return True

    def _normalize_once(self) -> bool:
        for account_index in range(self.topLevelItemCount()):
            account_item = self.topLevelItem(account_index)
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                if self.item_kind(group_item) == "session":
                    moved = account_item.takeChild(group_index)
                    self._ungrouped_group_for_account(account_item).addChild(moved)
                    return True
                if self.item_kind(group_item) != "group":
                    continue
                for child_index in range(group_item.childCount()):
                    child_item = group_item.child(child_index)
                    child_kind = self.item_kind(child_item)
                    if child_kind == "group":
                        moved = group_item.takeChild(child_index)
                        account_item.insertChild(account_item.indexOfChild(group_item) + 1, moved)
                        return True
                    if child_kind == "session" and child_item.childCount() > 0:
                        nested = child_item.takeChild(0)
                        if self.item_kind(nested) == "group":
                            account_item.insertChild(account_item.indexOfChild(group_item) + 1, nested)
                        else:
                            group_item.insertChild(group_item.indexOfChild(child_item) + 1, nested)
                        return True
        return False

    def _ungrouped_group_for_account(self, account_item: QTreeWidgetItem) -> QTreeWidgetItem:
        for index in range(account_item.childCount()):
            child = account_item.child(index)
            if child.data(0, Qt.ItemDataRole.UserRole) == UNGROUPED_CODE_GROUP_ID:
                return child
        group_item = _new_code_group_item(
            UNGROUPED_CODE_GROUP_LABEL,
            UNGROUPED_CODE_GROUP_ID,
            str(account_item.data(0, Qt.ItemDataRole.UserRole + 1) or ""),
        )
        account_item.addChild(group_item)
        return group_item

    def _visual_path(self, item: QTreeWidgetItem) -> tuple[int, ...]:
        path: list[int] = []
        current: QTreeWidgetItem | None = item
        while current is not None:
            parent = current.parent()
            if parent is None:
                path.append(self.indexOfTopLevelItem(current))
            else:
                path.append(parent.indexOfChild(current))
            current = parent
        return tuple(reversed(path))

    @staticmethod
    def _is_above_drop(position) -> bool:
        return str(position).endswith("AboveItem")


def build_account_item(
    label: str,
    column1: str,
    account_uuid: str,
    default_group_id: str,
    sessions_root,
) -> QTreeWidgetItem:
    account_item = QTreeWidgetItem([label, column1])
    account_item.setData(0, Qt.ItemDataRole.UserRole, account_uuid)
    account_item.setData(0, Qt.ItemDataRole.UserRole + 1, default_group_id)
    account_item.setData(0, Qt.ItemDataRole.UserRole + 2, sessions_root)
    account_item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsDropEnabled
    )
    return account_item


def build_session_item(session: ClaudeSession) -> QTreeWidgetItem:
    session_item = QTreeWidgetItem(
        [session.title, format_activity_timestamp(session.last_activity_at)]
    )
    session_item.setData(0, Qt.ItemDataRole.UserRole, session)
    session_item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsDragEnabled
    )
    return session_item


def build_ghost_session_item(session: ClaudeSession) -> QTreeWidgetItem:
    ghost = QTreeWidgetItem([session.title, tr("badge.copy")])
    ghost.setData(0, Qt.ItemDataRole.UserRole, session)
    ghost.setData(0, STAGED_MODE_ROLE, "copy")
    ghost.setForeground(1, QBrush(COPY_BADGE_COLOR))
    ghost.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return ghost


def build_ghost_group_marker(group_item: QTreeWidgetItem, staged_mode: str) -> None:
    group_item.setData(0, STAGED_MODE_ROLE, staged_mode)
    group_item.setForeground(1, QBrush(COPY_BADGE_COLOR))
    group_item.setText(1, tr("badge.copy"))


def _new_code_group_item(label: str, code_group_id: str, group_id: str) -> QTreeWidgetItem:
    group_item = QTreeWidgetItem([label, "Code group"])
    group_item.setData(0, Qt.ItemDataRole.UserRole, code_group_id)
    group_item.setData(0, Qt.ItemDataRole.UserRole + 1, group_id)
    group_item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsDragEnabled
        | Qt.ItemFlag.ItemIsDropEnabled
    )
    return group_item
