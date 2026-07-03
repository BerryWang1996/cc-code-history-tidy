from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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

from cc_history_tidy import i18n
from cc_history_tidy.account_config import (
    AccountLabelConfig,
    load_account_label_config,
)
from cc_history_tidy.backup import BackupSnapshot, create_backup, list_backups, restore_backup
from cc_history_tidy.code_groups import (
    UNGROUPED_CODE_GROUP_ID,
    save_code_group_layout_to_desktop_config,
)
from cc_history_tidy.i18n import tr
from cc_history_tidy.models import ClaudeSession, MigrationMode, ScannedAccount
from cc_history_tidy.migrator import migrate_sessions
from cc_history_tidy.paths import ClaudeEnvironment, discover_claude_environment
from cc_history_tidy.processes import is_claude_desktop_running
from cc_history_tidy.scanner import scan_accounts
from cc_history_tidy.session_tree import (
    STAGED_MODE_ROLE,
    SessionTreeWidget,
    _new_code_group_item,
    build_account_item,
    build_session_item,
)

SESSION_COUNT_ROLE = Qt.ItemDataRole.UserRole + 4


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
        settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        config_home = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".claude-desktop-migrator"
        self.settings_path = settings_path or (config_home / "settings.json")
        i18n.set_language(i18n.detect_default_language(self.settings_path))

        self.setWindowTitle(tr("app.title"))
        self.resize(1120, 720)

        self.status_label = QLabel(tr("app.initial_status"))
        self.session_tree = SessionTreeWidget()
        self.session_tree.setHeaderLabels([tr("header.tree"), tr("header.updated")])
        self.session_tree.setColumnWidth(0, 620)
        self.session_tree.header().setStretchLastSection(True)
        self.session_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.session_tree.setDragEnabled(True)
        self.session_tree.setAcceptDrops(True)
        self.session_tree.setDropIndicatorShown(True)
        self.session_tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.session_tree.setDefaultDropAction(Qt.DropAction.MoveAction)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton(tr("btn.scan"))
        self.dry_run_button = QPushButton(tr("btn.preview"))
        self.execute_button = QPushButton(tr("btn.execute"))
        self.undo_button = QPushButton(tr("btn.undo"))
        self.redo_button = QPushButton(tr("btn.redo"))
        self.reset_button = QPushButton(tr("btn.reset"))
        self.backups_button = QPushButton(tr("btn.backups"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        current_index = self.language_combo.findData(i18n.current_language())
        self.language_combo.setCurrentIndex(max(current_index, 0))
        action_row.addWidget(self.scan_button)
        action_row.addWidget(self.dry_run_button)
        action_row.addWidget(self.execute_button)
        action_row.addWidget(self.undo_button)
        action_row.addWidget(self.redo_button)
        action_row.addWidget(self.reset_button)
        action_row.addWidget(self.backups_button)
        action_row.addStretch(1)
        action_row.addWidget(self.language_combo)

        self.scan_button.clicked.connect(self.scan_default_environment)
        self.dry_run_button.clicked.connect(self.show_dry_run)
        self.execute_button.clicked.connect(self.execute_plan)
        self.undo_button.clicked.connect(self.session_tree.undo)
        self.redo_button.clicked.connect(self.session_tree.redo)
        self.reset_button.clicked.connect(self.reset_staged_changes)
        self.backups_button.clicked.connect(self.show_backups_dialog)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)

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
        self.backup_parent = backup_parent or (config_home / "backups")
        self.account_config_path = account_config_path or (config_home / "account-groups.json")
        self.account_config: AccountLabelConfig = load_account_label_config(self.account_config_path)
        self.process_checker = process_checker
        self.execute_confirmer = execute_confirmer
        self.session_tree.statusMessage.connect(self.status_label.setText)
        self.session_tree.treeChanged.connect(self._on_tree_changed)
        self.refresh_execute_state()
        self._refresh_undo_buttons()

    def scan_default_environment(self) -> None:
        try:
            self.load_environment(discover_claude_environment())
        except Exception as exc:  # pragma: no cover - exercised manually
            self.status_label.setText(tr("status.scan_failed", exc=exc))

    def load_environment(self, env: ClaudeEnvironment) -> None:
        self.env = env
        self.accounts = scan_accounts(env)
        self._populate_trees()
        self._loaded_tree_signature = self.tree_signature()
        self.refresh_execute_state()
        self._refresh_undo_buttons()
        self.status_label.setText(
            tr(
                "status.loaded",
                n=sum(len(account.sessions) for account in self.accounts),
                root=env.sessions_root,
            )
        )

    def show_dry_run(self) -> None:
        self.refresh_execute_state()
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
        copy_count = len(planned) - move_count
        layout_status = "yes" if has_tree_changes else "no"
        self.status_label.setText(
            tr("status.dry_run", moves=move_count, copies=copy_count, layout=layout_status)
        )

    def available_backups(self) -> list[BackupSnapshot]:
        return list_backups(self.backup_parent)

    def show_backups_dialog(self) -> None:
        backups = self.available_backups()
        if not backups:
            self.status_label.setText(tr("status.no_backups", path=self.backup_parent))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("dlg.backups_title"))
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for backup in backups:
            reason = backup.reason or "backup"
            item = QListWidgetItem(f"{backup.root.name}  [{reason}]  ->  {backup.sessions_root}")
            item.setData(Qt.ItemDataRole.UserRole, backup)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox()
        restore_button = buttons.addButton(
            tr("dlg.restore_selected"), QDialogButtonBox.ButtonRole.AcceptRole
        )
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
                    tr("dlg.claude_running_title"),
                    tr("dlg.restore_running_body"),
                )
                return
            answer = QMessageBox.question(
                dialog,
                tr("dlg.restore_title"),
                tr("dlg.restore_body", name=backup.root.name, path=backup.sessions_root),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            restore_backup(backup)
            if self.env is not None:
                self.load_environment(self.env)
            self.status_label.setText(tr("status.restored", name=backup.root.name))
            dialog.accept()

        restore_button.clicked.connect(restore_selected)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def refresh_execute_state(self) -> None:
        if self.process_checker():
            self.execute_button.setEnabled(False)
            self.execute_button.setToolTip(tr("tooltip.execute_disabled"))
        else:
            self.execute_button.setEnabled(True)
            self.execute_button.setToolTip(tr("tooltip.execute_enabled"))

    def _refresh_undo_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self.session_tree.undo_stack))
        self.redo_button.setEnabled(bool(self.session_tree.redo_stack))

    def _on_tree_changed(self) -> None:
        self._refresh_undo_buttons()
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        if planned or has_tree_changes:
            move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
            copy_count = len(planned) - move_count
            self.status_label.setText(
                tr("status.staged_summary", moves=move_count, copies=copy_count)
            )

    def _on_language_changed(self) -> None:
        code = self.language_combo.currentData()
        if not isinstance(code, str) or code == i18n.current_language():
            return
        i18n.set_language(code)
        try:
            i18n.save_language(code, self.settings_path)
        except OSError:  # pragma: no cover - settings dir not writable
            pass
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("app.title"))
        self.scan_button.setText(tr("btn.scan"))
        self.dry_run_button.setText(tr("btn.preview"))
        self.execute_button.setText(tr("btn.execute"))
        self.undo_button.setText(tr("btn.undo"))
        self.redo_button.setText(tr("btn.redo"))
        self.reset_button.setText(tr("btn.reset"))
        self.backups_button.setText(tr("btn.backups"))
        self.session_tree.setHeaderLabels([tr("header.tree"), tr("header.updated")])
        self.refresh_execute_state()
        tree = self.session_tree
        for account_index in range(tree.topLevelItemCount()):
            account_item = tree.topLevelItem(account_index)
            count = account_item.data(0, SESSION_COUNT_ROLE)
            if isinstance(count, int):
                account_item.setText(1, tr("tree.sessions_count", n=count))
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                if group_item.data(0, Qt.ItemDataRole.UserRole) == UNGROUPED_CODE_GROUP_ID:
                    group_item.setText(0, tr("tree.ungrouped"))
                if tree.is_ghost_item(group_item):
                    group_item.setText(1, tr("badge.copy"))
                elif tree.item_kind(group_item) == "group":
                    group_item.setText(1, tr("tree.group_type"))
                for session_index in range(group_item.childCount()):
                    session_item = group_item.child(session_index)
                    if tree.is_ghost_item(session_item):
                        session_item.setText(1, tr("badge.copy"))
        tree.refresh_staged_markers()
        self.status_label.setText(tr("status.language_changed"))

    def execute_plan(self) -> None:
        self.refresh_execute_state()
        if self.process_checker():
            self.status_label.setText(tr("status.close_claude_first"))
            QMessageBox.warning(
                self, tr("dlg.claude_running_title"), tr("dlg.claude_running_body")
            )
            return
        if self.env is None:
            self.status_label.setText(tr("status.scan_first"))
            return
        planned = self.planned_session_moves()
        has_tree_changes = self.tree_signature() != self._loaded_tree_signature
        if not planned and not has_tree_changes:
            self.status_label.setText(tr("status.no_staged"))
            return
        copied = 0
        removed = 0
        move_count = sum(1 for move in planned if move.mode == MigrationMode.MOVE)
        copy_count = len(planned) - move_count
        if not self._confirm_execution(
            self._execution_summary(move_count, copy_count, has_tree_changes)
        ):
            self.status_label.setText(tr("status.cancelled"))
            return

        visible_keys, layout_by_root = self.staged_code_group_layout_by_root()
        labels_by_root = self._group_labels_by_root()

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
            self.status_label.setText(tr("status.backup_failed", exc=exc))
            return

        by_move_target: dict[
            tuple[MigrationMode, Path, Path, str, str, str], list[PlannedSessionMove]
        ] = {}
        for move in planned:
            key = (
                move.mode,
                move.source_sessions_root,
                move.target_sessions_root,
                move.session.account_uuid,
                move.target_account_uuid,
                move.target_group_id,
            )
            by_move_target.setdefault(key, []).append(move)

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
            ), batch_moves in ordered_batches:
                result = migrate_sessions(
                    sessions_root=source_sessions_root,
                    source_account_uuid=source_account_uuid,
                    target_account_uuid=target_account_uuid,
                    session_files=[move.session.metadata_path for move in batch_moves],
                    mode=batch_mode,
                    backup_root=self.backup_parent,
                    target_group_id=target_group_id,
                    config_path=target_sessions_root.parent / "claude_desktop_config.json",
                    target_sessions_root=target_sessions_root,
                    reuse_backup=backups[source_sessions_root],
                )
                copied += len(result.copied)
                removed += len(result.removed)
                if batch_mode == MigrationMode.COPY and len(result.session_id_mapping) == len(
                    batch_moves
                ):
                    # Copies get fresh sessionIds; assign each new id to the
                    # code group the ghost was pasted into so the copy shows up
                    # grouped after the next Claude Desktop launch.
                    for move, (_old_id, new_id) in zip(batch_moves, result.session_id_mapping):
                        if move.target_code_group_id == UNGROUPED_CODE_GROUP_ID:
                            continue
                        assignments, order_data = layout_by_root.setdefault(
                            move.target_sessions_root, ({}, {})
                        )
                        session_key = f"code:{new_id}"
                        assignments[session_key] = move.target_code_group_id
                        order_data.setdefault(move.target_code_group_id, []).append(session_key)

            if has_tree_changes or copy_count:
                for root, (assignments, order_data) in layout_by_root.items():
                    save_code_group_layout_to_desktop_config(
                        root.parent / "claude_desktop_config.json",
                        visible_keys,
                        assignments,
                        order_data,
                        group_labels=labels_by_root.get(root),
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
                    tr(
                        "status.exec_failed_partial",
                        exc=exc,
                        n=len(restore_errors),
                        details="; ".join(restore_errors),
                        path=self.backup_parent,
                    )
                )
            else:
                self.status_label.setText(tr("status.exec_failed_rolled_back", exc=exc))
            return

        self.load_environment(self.env)
        self.status_label.setText(tr("status.executed", copied=copied, removed=removed))

    def _confirm_execution(self, summary: str) -> bool:
        if self.execute_confirmer is not None:
            return self.execute_confirmer(summary)
        answer = QMessageBox.question(self, tr("dlg.confirm_title"), summary)
        return answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def _execution_summary(move_count: int, copy_count: int, layout_changed: bool) -> str:
        parts = []
        if move_count:
            parts.append(tr("dlg.summary_move", n=move_count))
        if copy_count:
            parts.append(tr("dlg.summary_copy", n=copy_count))
        if layout_changed:
            parts.append(tr("dlg.summary_layout"))
        return tr("dlg.summary_head") + tr("dlg.summary_join").join(parts) + tr("dlg.summary_tail")

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

    def _group_labels_by_root(self) -> dict[Path, dict[str, str]]:
        labels_by_root: dict[Path, dict[str, str]] = {}
        for account_index in range(self.session_tree.topLevelItemCount()):
            account_item = self.session_tree.topLevelItem(account_index)
            sessions_root = account_item.data(0, Qt.ItemDataRole.UserRole + 2)
            if not isinstance(sessions_root, Path):
                continue
            labels = labels_by_root.setdefault(sessions_root, {})
            for group_index in range(account_item.childCount()):
                group_item = account_item.child(group_index)
                code_group_id = group_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(code_group_id, str) or code_group_id == UNGROUPED_CODE_GROUP_ID:
                    continue
                label = group_item.text(0).strip()
                if label:
                    labels[code_group_id] = label
        return labels_by_root

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

    def reset_staged_changes(self) -> None:
        self._populate_trees()
        self.refresh_execute_state()
        self._refresh_undo_buttons()
        self.status_label.setText(tr("status.reset_done"))

    def _populate_trees(self) -> None:
        self.session_tree.clear_clipboard()
        self.session_tree.clear_history()
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
            account_item = build_account_item(
                label,
                tr("tree.sessions_count", n=len(account.sessions)),
                account.partition.account_uuid,
                _default_group_id(account.sessions),
                account.partition.root.parent,
            )
            account_item.setData(0, SESSION_COUNT_ROLE, len(account.sessions))
            self.session_tree.addTopLevelItem(account_item)
            code_group_items: dict[str, QTreeWidgetItem] = {}
            for session in account.sessions:
                group_item = code_group_items.get(session.code_group_id)
                if group_item is None:
                    group_label = (
                        tr("tree.ungrouped")
                        if session.code_group_id == UNGROUPED_CODE_GROUP_ID
                        else session.code_group_label
                    )
                    group_item = _new_code_group_item(
                        group_label,
                        session.code_group_id,
                        session.group_id,
                    )
                    account_item.addChild(group_item)
                    group_item.setExpanded(True)
                    code_group_items[session.code_group_id] = group_item
                group_item.addChild(build_session_item(session))
            if UNGROUPED_CODE_GROUP_ID not in code_group_items:
                ungrouped_item = _new_code_group_item(
                    tr("tree.ungrouped"),
                    UNGROUPED_CODE_GROUP_ID,
                    _default_group_id(account.sessions),
                )
                account_item.addChild(ungrouped_item)
                ungrouped_item.setExpanded(True)
            account_item.setExpanded(True)
        self._refresh_undo_buttons()


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
