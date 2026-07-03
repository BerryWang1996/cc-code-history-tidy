from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cc_history_tidy.code_groups import (
    UNGROUPED_CODE_GROUP_ID,
    UNGROUPED_CODE_GROUP_LABEL,
)
from cc_history_tidy.models import ClaudeSession, MigrationMode

STAGED_MODE_ROLE = Qt.ItemDataRole.UserRole + 3

CUT_DIM_COLOR = QColor(150, 150, 150)
MOVE_BADGE_COLOR = QColor(30, 100, 200)
COPY_BADGE_COLOR = QColor(30, 140, 60)
MOVE_BADGE_TEXT = "待移入"
COPY_BADGE_TEXT = "⊕ 待复制"


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
            self.statusMessage.emit(f"已剪切 {len(items)} 个对话——右键目标分组粘贴 (Ctrl+V)。")
        else:
            self.statusMessage.emit(f"已复制 {len(items)} 个对话——右键目标分组粘贴 (Ctrl+V)。")
        return len(items)

    def clear_clipboard(self) -> None:
        for item in self.clipboard_items:
            try:
                self._set_item_dimmed(item, False)
            except RuntimeError:
                pass  # item was destroyed by a tree rebuild
        self.clipboard_items = []
        self.clipboard_mode = None

    def is_ghost_item(self, item: QTreeWidgetItem) -> bool:
        return item.data(0, STAGED_MODE_ROLE) == "copy"

    @staticmethod
    def _set_item_dimmed(item: QTreeWidgetItem, dimmed: bool) -> None:
        brush = QBrush(CUT_DIM_COLOR) if dimmed else QBrush()
        item.setForeground(0, brush)
        item.setForeground(1, brush)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        moving_items = self._selected_movable_items()
        target_item = self._drop_target_item(event)
        if moving_items and target_item is not None and self.move_items_to_target(
            moving_items,
            target_item,
            self.dropIndicatorPosition(),
        ):
            self.normalize_structure()
            event.acceptProposedAction()
            return
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
        return self._move_items_under_parent(moving_items, target_account, insert_index)

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
