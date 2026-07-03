from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QComboBox,
    QPushButton,
    QTreeWidgetItem,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cc_history_tidy.account_config import (
    AccountLabelConfig,
    load_account_label_config,
)
from cc_history_tidy.backup import BackupSnapshot, create_backup, list_backups, restore_backup
from cc_history_tidy.code_groups import (
    UNGROUPED_CODE_GROUP_ID,
    UNGROUPED_CODE_GROUP_LABEL,
    save_code_group_layout_to_desktop_config,
)
from cc_history_tidy.models import ClaudeSession, MigrationMode, ScannedAccount
from cc_history_tidy.migrator import migrate_sessions
from cc_history_tidy.paths import ClaudeEnvironment, discover_claude_environment
from cc_history_tidy.processes import is_claude_desktop_running
from cc_history_tidy.scanner import scan_accounts


def create_app(argv: list[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication(argv or [])


@dataclass(frozen=True)
class PlannedSessionMove:
    session: ClaudeSession
    source_sessions_root: Path
    target_sessions_root: Path
    target_account_uuid: str
    target_group_id: str
    target_code_group_id: str


class SessionTreeWidget(QTreeWidget):
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


class MainWindow(QMainWindow):
    def __init__(
        self,
        backup_parent: Path | None = None,
        account_config_path: Path | None = None,
        process_checker: Callable[[], bool] = is_claude_desktop_running,
    ) -> None:
        super().__init__()
        self.setWindowTitle("CC Code History Tidy")
        self.resize(1120, 720)

        self.status_label = QLabel("Scan Claude Desktop Code sessions, then stage migrations.")
        self.session_tree = SessionTreeWidget()
        self.session_tree.setHeaderLabels(["Account / Code group / Conversation", "Updated"])
        self.session_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.session_tree.setDragEnabled(True)
        self.session_tree.setAcceptDrops(True)
        self.session_tree.setDropIndicatorShown(True)
        self.session_tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.session_tree.setDefaultDropAction(Qt.DropAction.MoveAction)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("Scan")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Copy", MigrationMode.COPY)
        self.mode_combo.addItem("Move", MigrationMode.MOVE)
        self.dry_run_button = QPushButton("Dry-run")
        self.execute_button = QPushButton("Execute")
        self.backups_button = QPushButton("Backups")
        action_row.addWidget(self.scan_button)
        action_row.addWidget(self.mode_combo)
        action_row.addWidget(self.dry_run_button)
        action_row.addWidget(self.execute_button)
        action_row.addWidget(self.backups_button)
        action_row.addStretch(1)

        self.scan_button.clicked.connect(self.scan_default_environment)
        self.dry_run_button.clicked.connect(self.show_dry_run)
        self.execute_button.clicked.connect(self.execute_plan)
        self.backups_button.clicked.connect(self.show_backups_dialog)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.session_tree, 1)
        layout.addLayout(action_row)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.env: ClaudeEnvironment | None = None
        self.accounts: list[ScannedAccount] = []
        self._loaded_tree_signature: tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = ()
        self.backup_parent = backup_parent or (
            Path(os.environ.get("USERPROFILE", str(Path.home())))
            / ".claude-desktop-migrator"
            / "backups"
        )
        self.account_config_path = account_config_path or (
            Path(os.environ.get("USERPROFILE", str(Path.home())))
            / ".claude-desktop-migrator"
            / "account-groups.json"
        )
        self.account_config: AccountLabelConfig = load_account_label_config(self.account_config_path)
        self.process_checker = process_checker
        self.refresh_execute_state()

    def scan_default_environment(self) -> None:
        try:
            self.load_environment(discover_claude_environment())
        except Exception as exc:  # pragma: no cover - exercised manually
            self.status_label.setText(f"Scan failed: {exc}")

    def load_environment(self, env: ClaudeEnvironment) -> None:
        self.env = env
        self.accounts = scan_accounts(env)
        self._populate_trees()
        self._loaded_tree_signature = self.tree_signature()
        self.refresh_execute_state()
        self.status_label.setText(
            f"Loaded {sum(len(account.sessions) for account in self.accounts)} sessions "
            f"from {env.sessions_root}"
        )

    def show_dry_run(self) -> None:
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        layout_status = "yes" if has_tree_changes else "no"
        self.status_label.setText(f"Dry-run: {len(planned)} file move(s); layout update: {layout_status}.")

    def show_not_implemented(self) -> None:
        QMessageBox.information(self, "Not wired yet", "This action will be wired after core scanning.")

    def available_backups(self) -> list[BackupSnapshot]:
        return list_backups(self.backup_parent)

    def show_backups_dialog(self) -> None:
        backups = self.available_backups()
        if not backups:
            self.status_label.setText(f"No backups found in {self.backup_parent}.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Backups")
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for backup in backups:
            item = QListWidgetItem(backup.root.name)
            item.setData(Qt.ItemDataRole.UserRole, backup)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox()
        restore_button = buttons.addButton("Restore Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        def restore_selected() -> None:
            item = list_widget.currentItem()
            if item is None:
                return
            backup = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(backup, BackupSnapshot):
                return
            answer = QMessageBox.question(
                dialog,
                "Restore backup",
                f"Restore backup {backup.root.name}? This replaces the current claude-code-sessions tree.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            restore_backup(backup)
            if self.env is not None:
                self.load_environment(self.env)
            self.status_label.setText(f"Restored backup {backup.root.name}.")
            dialog.accept()

        restore_button.clicked.connect(restore_selected)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def refresh_execute_state(self) -> None:
        if self.process_checker():
            self.execute_button.setEnabled(False)
            self.execute_button.setToolTip("Close Claude Desktop / Claude Code Desktop before executing changes.")
        else:
            self.execute_button.setEnabled(True)
            self.execute_button.setToolTip("Execute staged tree changes.")

    def execute_plan(self) -> None:
        self.refresh_execute_state()
        if self.process_checker():
            self.status_label.setText("Close Claude Desktop before migrating.")
            QMessageBox.warning(self, "Claude Desktop is running", "Close Claude Desktop before migrating.")
            return
        if self.env is None:
            self.status_label.setText("Scan before migrating.")
            return
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        if not planned and not has_tree_changes:
            self.status_label.setText("No staged changes.")
            return
        copied = 0
        removed = 0
        config_path = self.env.sessions_root.parent / "claude_desktop_config.json"
        try:
            execution_backup = create_backup(
                self.env.sessions_root,
                self.backup_parent,
                reason="execute",
                config_path=config_path,
            )
        except Exception as exc:
            self.status_label.setText(f"Backup failed; execution cancelled: {exc}")
            return
        by_move_target: dict[tuple[Path, Path, str, str, str], list[ClaudeSession]] = {}
        for move in planned:
            key = (
                move.source_sessions_root,
                move.target_sessions_root,
                move.session.account_uuid,
                move.target_account_uuid,
                move.target_group_id,
            )
            by_move_target.setdefault(key, []).append(move.session)

        try:
            for (
                source_sessions_root,
                target_sessions_root,
                source_account_uuid,
                target_account_uuid,
                target_group_id,
            ), sessions in by_move_target.items():
                result = migrate_sessions(
                    sessions_root=source_sessions_root,
                    source_account_uuid=source_account_uuid,
                    target_account_uuid=target_account_uuid,
                    session_files=[session.metadata_path for session in sessions],
                    mode=self.selected_migration_mode(),
                    backup_root=self.backup_parent,
                    target_group_id=target_group_id,
                    config_path=target_sessions_root.parent / "claude_desktop_config.json",
                    target_sessions_root=target_sessions_root,
                )
                copied += len(result.copied)
                removed += len(result.removed)

            if has_tree_changes:
                visible_keys, assignments, order_data = self.staged_code_group_layout()
                save_code_group_layout_to_desktop_config(
                    config_path,
                    visible_keys,
                    assignments,
                    order_data,
                )
        except Exception as exc:
            restore_backup(execution_backup)
            self.load_environment(self.env)
            self.status_label.setText(f"Execution failed and rolled back: {exc}")
            return

        self.load_environment(self.env)
        self.status_label.setText(f"Executed {copied} file move(s); removed {removed} source metadata file(s).")

    def selected_migration_mode(self) -> MigrationMode:
        mode = self.mode_combo.currentData()
        if isinstance(mode, MigrationMode):
            return mode
        try:
            return MigrationMode(str(mode))
        except ValueError:
            return MigrationMode.COPY

    def planned_session_moves(self) -> list[PlannedSessionMove]:
        moves: list[PlannedSessionMove] = []
        for account_index in range(self.session_tree.topLevelItemCount()):
            account_item = self.session_tree.topLevelItem(account_index)
            account_uuid = account_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(account_uuid, str):
                continue
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                code_group_id = group_item.data(0, Qt.ItemDataRole.UserRole)
                group_id = group_item.data(0, Qt.ItemDataRole.UserRole + 1)
                if not isinstance(code_group_id, str):
                    continue
                if not isinstance(group_id, str):
                    continue
                target_sessions_root = account_item.data(0, Qt.ItemDataRole.UserRole + 2)
                if not isinstance(target_sessions_root, Path):
                    continue
                for session_index in range(group_item.childCount()):
                    session_item = group_item.child(session_index)
                    session = session_item.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(session, ClaudeSession):
                        continue
                    target_group_id = self._target_filesystem_group_id(account_item, group_id, session, account_uuid)
                    if session.account_uuid != account_uuid or session.group_id != target_group_id:
                        moves.append(
                            PlannedSessionMove(
                                session=session,
                                source_sessions_root=session.sessions_root,
                                target_sessions_root=target_sessions_root,
                                target_account_uuid=account_uuid,
                                target_group_id=target_group_id,
                                target_code_group_id=code_group_id,
                            )
                        )
        return moves

    def tree_signature(self) -> tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...]:
        accounts: list[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = []
        for account_index in range(self.session_tree.topLevelItemCount()):
            account_item = self.session_tree.topLevelItem(account_index)
            account_uuid = account_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(account_uuid, str):
                continue
            groups: list[tuple[str, tuple[str, ...]]] = []
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                code_group_id = group_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(code_group_id, str):
                    continue
                session_ids: list[str] = []
                for session_index in range(group_item.childCount()):
                    session = group_item.child(session_index).data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(session, ClaudeSession):
                        session_ids.append(session.session_id)
                groups.append((code_group_id, tuple(session_ids)))
            accounts.append((account_uuid, tuple(groups)))
        return tuple(accounts)

    def staged_code_group_layout(self) -> tuple[set[str], dict[str, str], dict[str, list[str]]]:
        visible_keys: set[str] = set()
        assignments: dict[str, str] = {}
        order_data: dict[str, list[str]] = {}
        for account_index in range(self.session_tree.topLevelItemCount()):
            account_item = self.session_tree.topLevelItem(account_index)
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                code_group_id = group_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(code_group_id, str):
                    continue
                if code_group_id != UNGROUPED_CODE_GROUP_ID:
                    order_data.setdefault(code_group_id, [])
                for session_index in range(group_item.childCount()):
                    session = group_item.child(session_index).data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(session, ClaudeSession):
                        continue
                    session_key = f"code:{session.session_id}"
                    visible_keys.add(session_key)
                    if code_group_id == UNGROUPED_CODE_GROUP_ID:
                        continue
                    assignments[session_key] = code_group_id
                    order_data.setdefault(code_group_id, []).append(session_key)
        return visible_keys, assignments, order_data

    def _target_filesystem_group_id(
        self,
        account_item: QTreeWidgetItem,
        group_id: str,
        session: ClaudeSession,
        target_account_uuid: str,
    ) -> str:
        if session.account_uuid != target_account_uuid:
            default_group_id = account_item.data(0, Qt.ItemDataRole.UserRole + 1)
            return default_group_id if isinstance(default_group_id, str) and default_group_id else group_id
        return group_id

    def _populate_trees(self) -> None:
        self.session_tree.clear()
        for account in self.accounts:
            display = self.account_config.display_for(account.partition.account_uuid)
            account_item = QTreeWidgetItem(
                [display.label, f"{len(account.sessions)} session(s)"]
            )
            account_item.setData(0, Qt.ItemDataRole.UserRole, account.partition.account_uuid)
            account_item.setData(0, Qt.ItemDataRole.UserRole + 1, _default_group_id(account.sessions))
            account_item.setData(0, Qt.ItemDataRole.UserRole + 2, account.partition.root.parent)
            account_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            self.session_tree.addTopLevelItem(account_item)
            code_group_items: dict[str, QTreeWidgetItem] = {}
            for session in account.sessions:
                group_item = code_group_items.get(session.code_group_id)
                if group_item is None:
                    group_item = _new_code_group_item(
                        session.code_group_label,
                        session.code_group_id,
                        session.group_id,
                    )
                    account_item.addChild(group_item)
                    group_item.setExpanded(True)
                    code_group_items[session.code_group_id] = group_item
                session_item = QTreeWidgetItem([session.title, str(session.last_activity_at or "")])
                session_item.setData(0, Qt.ItemDataRole.UserRole, session)
                session_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                group_item.addChild(session_item)
            if UNGROUPED_CODE_GROUP_ID not in code_group_items:
                ungrouped_item = _new_code_group_item(
                    UNGROUPED_CODE_GROUP_LABEL,
                    UNGROUPED_CODE_GROUP_ID,
                    _default_group_id(account.sessions),
                )
                account_item.addChild(ungrouped_item)
                ungrouped_item.setExpanded(True)
            account_item.setExpanded(True)


def run_app(argv: list[str] | None = None) -> int:
    app = create_app(argv or sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


def _default_group_id(sessions: tuple[ClaudeSession, ...]) -> str:
    for session in sessions:
        if session.group_id:
            return session.group_id
    return ""


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
