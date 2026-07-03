from __future__ import annotations

import json
from pathlib import Path

from cc_history_tidy.paths import ClaudeEnvironment


def resolve_group_labels(env: ClaudeEnvironment) -> dict[str, str]:
    labels: dict[str, str] = {}
    _merge_label_from_claude_config(labels, env.claude_config)

    for sessions_root in env.sessions_roots:
        local_agent_root = sessions_root.parent / "local-agent-mode-sessions"
        if local_agent_root.exists():
            for config_path in local_agent_root.rglob(".claude.json"):
                _merge_label_from_claude_config(labels, config_path)

    return labels


def _merge_label_from_claude_config(labels: dict[str, str], config_path: Path) -> None:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    account = data.get("oauthAccount")
    if not isinstance(account, dict):
        return
    group_id = account.get("organizationUuid")
    if not isinstance(group_id, str) or not group_id:
        return
    label = _label_from_account(account)
    if label and (group_id not in labels or _looks_like_better_label(label, labels[group_id])):
        labels[group_id] = label


def _label_from_account(account: dict[str, object]) -> str:
    for key in ("organizationName", "displayName", "emailAddress"):
        value = account.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _looks_like_better_label(candidate: str, existing: str) -> bool:
    if "@" in candidate and "@" not in existing:
        return False
    if "@" in existing and "@" not in candidate:
        return True
    return len(candidate) > len(existing)
