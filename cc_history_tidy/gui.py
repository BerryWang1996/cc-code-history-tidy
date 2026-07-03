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
from cc_history_tidy.session_tree import (
    STAGED_MODE_ROLE,
    SessionTreeWidget,
    _new_code_group_item,
    format_activity_timestamp,
)


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
    mode: MigrationMode


class MainWindow(QMainWindow):
    def __init__(
        self,
        backup_parent: Path | None = None,
        account_config_path: Path | None = None,
        process_checker: Callable[[], bool] = is_claude_desktop_running,
        execute_confirmer: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("CC Code History Tidy")
        self.resize(1120, 720)

        self.status_label = QLabel("点击 扫描 载入 Claude Desktop Code 会话，然后用 复制/剪切/粘贴 或拖拽整理。")
        self.session_tree = SessionTreeWidget()
        self.session_tree.setHeaderLabels(["账户 / Code 分组 / 对话", "更新时间"])
        self.session_tree.setColumnWidth(0, 620)
        self.session_tree.header().setStretchLastSection(True)
        self.session_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.session_tree.setDragEnabled(True)
        self.session_tree.setAcceptDrops(True)
        self.session_tree.setDropIndicatorShown(True)
        self.session_tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.session_tree.setDefaultDropAction(Qt.DropAction.MoveAction)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("扫描")
        self.dry_run_button = QPushButton("预览")
        self.execute_button = QPushButton("执行")
        self.backups_button = QPushButton("备份")
        action_row.addWidget(self.scan_button)
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
        self.execute_confirmer = execute_confirmer
        self.session_tree.statusMessage.connect(self.status_label.setText)
        self.refresh_execute_state()

    def scan_default_environment(self) -> None:
        try:
            self.load_environment(discover_claude_environment())
        except Exception as exc:  # pragma: no cover - exercised manually
            self.status_label.setText(f"扫描失败：{exc}")

    def load_environment(self, env: ClaudeEnvironment) -> None:
        self.env = env
        self.accounts = scan_accounts(env)
        self._populate_trees()
        self._loaded_tree_signature = self.tree_signature()
        self.refresh_execute_state()
        self.status_label.setText(
            f"已加载 {sum(len(account.sessions) for account in self.accounts)} 个会话（{env.sessions_root}）"
        )

    def show_dry_run(self) -> None:
        self.refresh_execute_state()
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
        copy_count = len(planned) - move_count
        layout_status = "yes" if has_tree_changes else "no"
        self.status_label.setText(
            f"预览：{move_count} 个移动、{copy_count} 个复制；布局更新：{layout_status}。（未写入磁盘）"
        )

    def show_not_implemented(self) -> None:
        QMessageBox.information(self, "Not wired yet", "This action will be wired after core scanning.")

    def available_backups(self) -> list[BackupSnapshot]:
        return list_backups(self.backup_parent)

    def show_backups_dialog(self) -> None:
        backups = self.available_backups()
        if not backups:
            self.status_label.setText(f"在 {self.backup_parent} 未找到备份。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("备份")
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for backup in backups:
            reason = backup.reason or "backup"
            item = QListWidgetItem(f"{backup.root.name}  [{reason}]  ->  {backup.sessions_root}")
            item.setData(Qt.ItemDataRole.UserRole, backup)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox()
        restore_button = buttons.addButton("恢复所选", QDialogButtonBox.ButtonRole.AcceptRole)
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
            if self.process_checker():
                QMessageBox.warning(
                    dialog,
                    "Claude 正在运行",
                    "请先关闭 Claude Desktop / Claude Code Desktop 再恢复备份。",
                )
                return
            answer = QMessageBox.question(
                dialog,
                "恢复备份",
                f"恢复备份 {backup.root.name}？\n\n"
                f"这将替换以下目录的会话树：\n{backup.sessions_root}",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            restore_backup(backup)
            if self.env is not None:
                self.load_environment(self.env)
            self.status_label.setText(f"已恢复备份 {backup.root.name}。")
            dialog.accept()

        restore_button.clicked.connect(restore_selected)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def refresh_execute_state(self) -> None:
        if self.process_checker():
            self.execute_button.setEnabled(False)
            self.execute_button.setToolTip(
                "请先关闭 Claude Desktop / Claude Code Desktop 再执行。"
                "注意：Claude Code CLI 也以 claude.exe 运行，会触发此检查。"
            )
        else:
            self.execute_button.setEnabled(True)
            self.execute_button.setToolTip("执行暂存的变更（会先弹出确认框）。")

    def execute_plan(self) -> None:
        self.refresh_execute_state()
        if self.process_checker():
            self.status_label.setText("请先关闭 Claude Desktop。")
            QMessageBox.warning(self, "Claude 正在运行", "请先关闭 Claude Desktop 再执行迁移。")
            return
        if self.env is None:
            self.status_label.setText("请先扫描。")
            return
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        if not planned and not has_tree_changes:
            self.status_label.setText("没有暂存的修改。")
            return
        copied = 0
        removed = 0
        move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
        copy_count = len(planned) - move_count
        if not self._confirm_execution(
            self._execution_summary(move_count, copy_count, has_tree_changes)
        ):
            self.status_label.setText("已取消，未做任何更改。")
            return

        visible_keys, layout_by_root = self.staged_code_group_layout_by_root()

        # Every root that is read from or written to during this execution gets
        # its own backup so a failure can roll back all of them, not just the
        # primary root.
        involved_roots: set[Path] = {self.env.sessions_root}
        for move in planned:
            involved_roots.add(move.source_sessions_root)
            involved_roots.add(move.target_sessions_root)
        if has_tree_changes:
            involved_roots.update(layout_by_root.keys())

        backups: dict[Path, BackupSnapshot] = {}
        try:
            for root in sorted(involved_roots):
                backups[root] = create_backup(
                    root,
                    self.backup_parent,
                    reason="execute",
                    config_path=root.parent / "claude_desktop_config.json",
                )
        except Exception as exc:
            self.status_label.setText(f"备份失败，执行已取消：{exc}")
            return

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

        # COPY batches run before MOVE batches so a session that is both copied
        # and moved in one execute is copied from its original location first.
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
                copied += len(result.copied)
                removed += len(result.removed)

            if has_tree_changes:
                for root, (assignments, order_data) in layout_by_root.items():
                    save_code_group_layout_to_desktop_config(
                        root.parent / "claude_desktop_config.json",
                        visible_keys,
                        assignments,
                        order_data,
                    )
        except Exception as exc:
            restore_errors: list[str] = []
            for root, backup in backups.items():
                try:
                    restore_backup(backup)
                except Exception as restore_exc:  # pragma: no cover - disk-level failure
                    restore_errors.append(f"{root}: {restore_exc}")
            self.load_environment(self.env)
            if restore_errors:
                self.status_label.setText(
                    f"执行失败：{exc}。有 {len(restore_errors)} 个目录回滚失败（{'; '.join(restore_errors)}），"
                    f"请从 {self.backup_parent} 手动恢复。"
                )
            else:
                self.status_label.setText(f"执行失败，已全部回滚：{exc}")
            return

        self.load_environment(self.env)
        self.status_label.setText(f"执行完成：写入 {copied} 个文件，移除 {removed} 个源文件。")

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
                    # Ghost items are staged copies and always produce a COPY,
                    # even inside the same account. For everything else, only a
                    # change of account or install root moves files on disk —
                    # regrouping between code groups is a layout-only edit.
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

    def staged_code_group_layout_by_root(
        self,
    ) -> tuple[set[str], dict[Path, tuple[dict[str, str], dict[str, list[str]]]]]:
        """Collect the staged layout, partitioned by sessions root.

        Each Claude install root has its own claude_desktop_config.json, so
        assignments/order must be written to the config of the root the account
        lives in. The visible-key set stays global so a session migrated to a
        different root is purged from its old root's config. Ghost-copy items
        are skipped: the copy gets a fresh sessionId at execute time, so the
        old id must neither be reassigned nor purged.
        """
        visible_keys: set[str] = set()
        by_root: dict[Path, tuple[dict[str, str], dict[str, list[str]]]] = {}
        for account_index in range(self.session_tree.topLevelItemCount()):
            account_item = self.session_tree.topLevelItem(account_index)
            sessions_root = account_item.data(0, Qt.ItemDataRole.UserRole + 2)
            if not isinstance(sessions_root, Path):
                continue
            assignments, order_data = by_root.setdefault(sessions_root, ({}, {}))
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                code_group_id = group_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(code_group_id, str):
                    continue
                if code_group_id != UNGROUPED_CODE_GROUP_ID:
                    order_data.setdefault(code_group_id, [])
                for session_index in range(group_item.childCount()):
                    session_item = group_item.child(session_index)
                    session = session_item.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(session, ClaudeSession):
                        continue
                    if session_item.data(0, STAGED_MODE_ROLE) == "copy":
                        continue
                    session_key = f"code:{session.session_id}"
                    visible_keys.add(session_key)
                    if code_group_id == UNGROUPED_CODE_GROUP_ID:
                        continue
                    assignments[session_key] = code_group_id
                    order_data.setdefault(code_group_id, []).append(session_key)
        return visible_keys, by_root

    def _target_filesystem_group_id(
        self,
        account_item: QTreeWidgetItem,
        group_id: str,
        session: ClaudeSession,
    ) -> str:
        # Sessions must always land under <account>/<group>/; a file directly
        # under the account root is invisible to Claude Desktop. Prefer the
        # target account's own group dir, then the tree group's, then keep the
        # session's original group dir.
        default_group_id = account_item.data(0, Qt.ItemDataRole.UserRole + 1)
        for candidate in (default_group_id, group_id, session.group_id):
            if isinstance(candidate, str) and candidate:
                return candidate
        return session.group_id

    def _populate_trees(self) -> None:
        self.session_tree.clear_clipboard()
        self.session_tree.clear()
        uuid_counts: dict[str, int] = {}
        for account in self.accounts:
            uuid_counts[account.partition.account_uuid] = (
                uuid_counts.get(account.partition.account_uuid, 0) + 1
            )
        for account in self.accounts:
            display = self.account_config.display_for(account.partition.account_uuid)
            label = display.label
            if uuid_counts[account.partition.account_uuid] > 1:
                # Same account signed into several Claude installs: make the
                # duplicate tree items distinguishable by their install root.
                label = f"{label} [{account.partition.root.parent.parent.name}]"
            account_item = QTreeWidgetItem(
                [label, f"{len(account.sessions)} session(s)"]
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
                session_item = QTreeWidgetItem([session.title, format_activity_timestamp(session.last_activity_at)])
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
