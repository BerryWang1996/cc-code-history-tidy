"""Structured snapshots of the session tree for undo/redo/reset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt

from cc_history_tidy.models import ClaudeSession

STAGED_MODE_ROLE = Qt.ItemDataRole.UserRole + 3
SESSION_COUNT_ROLE = Qt.ItemDataRole.UserRole + 4


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
    session_count: int | None
    groups: tuple[GroupState, ...]


@dataclass(frozen=True)
class TreeState:
    accounts: tuple[AccountState, ...]


def capture_tree_state(tree) -> TreeState:
    accounts: list[AccountState] = []
    for account_index in range(tree.topLevelItemCount()):
        account_item = tree.topLevelItem(account_index)
        groups: list[GroupState] = []
        for group_index in range(account_item.childCount()):
            group_item = account_item.child(group_index)
            sessions: list[SessionState] = []
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
                session_count=account_item.data(0, SESSION_COUNT_ROLE),
                groups=tuple(groups),
            )
        )
    return TreeState(accounts=tuple(accounts))


def restore_tree_state(tree, state: TreeState) -> None:
    from cc_history_tidy.session_tree import (
        _new_code_group_item,
        build_account_item,
        build_ghost_group_marker,
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
        if account_state.session_count is not None:
            account_item.setData(0, SESSION_COUNT_ROLE, account_state.session_count)
        for group_state in account_state.groups:
            group_item = _new_code_group_item(
                group_state.label, group_state.code_group_id, group_state.group_id
            )
            if group_state.staged_mode:
                build_ghost_group_marker(group_item, group_state.staged_mode)
            account_item.addChild(group_item)
            for session_state in group_state.sessions:
                if session_state.staged_mode == "copy":
                    group_item.addChild(build_ghost_session_item(session_state.session))
                else:
                    group_item.addChild(build_session_item(session_state.session))
            group_item.setExpanded(group_state.expanded)
        account_item.setExpanded(account_state.expanded)
    tree.refresh_staged_markers()
