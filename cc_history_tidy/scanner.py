from __future__ import annotations

import json
from pathlib import Path

from cc_history_tidy.account_identity import collect_account_emails, gateway_server_url
from cc_history_tidy.models import AccountPartition, ClaudeSession, ScannedAccount
from cc_history_tidy.paths import ClaudeEnvironment
from cc_history_tidy.group_labels import resolve_group_labels
from cc_history_tidy.code_groups import (
    UNGROUPED_CODE_GROUP_ID,
    CodeGroupLayout,
    load_code_group_layout,
)


def scan_accounts(env: ClaudeEnvironment) -> list[ScannedAccount]:
    transcript_index = _index_transcripts(env.transcript_root)
    group_labels = resolve_group_labels(env)
    account_emails = collect_account_emails(env)
    accounts: list[ScannedAccount] = []
    for sessions_root in env.sessions_roots:
        root_env = ClaudeEnvironment(
            user_profile=env.user_profile,
            appdata=env.appdata,
            localappdata=env.localappdata,
            claude_config=env.claude_config,
            transcript_root=env.transcript_root,
            sessions_root=sessions_root,
            sessions_roots=env.sessions_roots,
            current_account_uuid=env.current_account_uuid,
        )
        code_groups = load_code_group_layout(root_env)
        root_accounts: list[tuple[AccountPartition, tuple[ClaudeSession, ...]]] = []
        for account_dir in sorted(p for p in sessions_root.iterdir() if p.is_dir()):
            partition = AccountPartition(
                account_uuid=account_dir.name,
                root=account_dir,
                is_current=account_dir.name == env.current_account_uuid,
            )
            sessions = tuple(
                sorted(
                    _scan_sessions(account_dir, sessions_root, transcript_index, group_labels, code_groups),
                    key=lambda session: (
                        session.code_group_order,
                        session.code_session_order,
                        -(session.last_activity_at or 0),
                        session.title,
                    ),
                )
            )
            root_accounts.append((partition, sessions))
        empty_groups = _empty_code_groups(code_groups, root_accounts)
        gateway_url = gateway_server_url(sessions_root.parent)
        for partition, sessions in root_accounts:
            accounts.append(
                ScannedAccount(
                    partition=partition,
                    sessions=sessions,
                    empty_code_groups=empty_groups,
                    email=account_emails.get(partition.account_uuid, ""),
                    gateway_url=gateway_url,
                )
            )
    return accounts


def _empty_code_groups(
    code_groups: CodeGroupLayout,
    root_accounts: list[tuple[AccountPartition, tuple[ClaudeSession, ...]]],
) -> tuple[tuple[str, str], ...]:
    """Layout-defined groups with no sessions anywhere in the root.

    Claude Desktop keeps showing these in its sidebar, so the tree must show
    them too (and they are valid paste/drag targets)."""
    used = {
        session.code_group_id
        for _, sessions in root_accounts
        for session in sessions
    }
    catalog: list[str] = list(code_groups.group_order)
    for group_id in code_groups.labels:
        if group_id not in catalog:
            catalog.append(group_id)
    return tuple(
        (group_id, code_groups.label_for_group(group_id))
        for group_id in catalog
        if group_id not in used and group_id != UNGROUPED_CODE_GROUP_ID
    )


def _index_transcripts(transcript_root: Path) -> dict[str, Path]:
    if not transcript_root.exists():
        return {}
    return {path.stem: path for path in transcript_root.rglob("*.jsonl")}


def _scan_sessions(
    account_dir: Path,
    sessions_root: Path,
    transcript_index: dict[str, Path],
    group_labels: dict[str, str],
    code_groups: CodeGroupLayout,
) -> list[ClaudeSession]:
    sessions: list[ClaudeSession] = []
    for metadata_path in sorted(account_dir.rglob("*.json")):
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        session_id = data.get("sessionId")
        cli_session_id = data.get("cliSessionId")
        if not session_id or not cli_session_id:
            continue
        relative = metadata_path.relative_to(account_dir)
        group_id = relative.parts[0] if len(relative.parts) > 1 else ""
        code_group_id = code_groups.group_for_session(session_id)
        sessions.append(
            ClaudeSession(
                metadata_path=metadata_path,
                sessions_root=sessions_root,
                account_uuid=account_dir.name,
                session_id=session_id,
                cli_session_id=cli_session_id,
                group_id=group_id,
                title=data.get("title") or cli_session_id,
                cwd=data.get("cwd") or "",
                created_at=data.get("createdAt"),
                last_activity_at=data.get("lastActivityAt"),
                archived=bool(data.get("isArchived", False)),
                transcript_path=transcript_index.get(cli_session_id),
                group_label=group_labels.get(group_id, group_id or "(root)"),
                code_group_id=code_group_id,
                code_group_label=code_groups.label_for_group(code_group_id),
                code_group_order=code_groups.order_for_group(code_group_id),
                code_session_order=code_groups.order_for_session(session_id),
            )
        )
    return sessions
