"""Resolve human-friendly identity for scanned accounts.

- Account emails come from ``~/.claude.json`` (current CLI login) and from the
  ``local-agent-mode-sessions/**/.claude.json`` snapshots each Claude install
  keeps per agent session — together they usually cover every account dir.
- Gateway installs are recognized by ``deploymentMode == "3p"`` in the root's
  ``claude_desktop_config.json``; their server URL lives in the
  ``host-creds-*.json`` files (``env.ANTHROPIC_BASE_URL``).
"""

from __future__ import annotations

import json
from pathlib import Path

from cc_history_tidy.paths import ClaudeEnvironment


def collect_account_emails(env: ClaudeEnvironment) -> dict[str, str]:
    emails: dict[str, str] = {}
    _merge_email_from_claude_config(emails, env.claude_config)
    for sessions_root in env.sessions_roots:
        local_agent_root = sessions_root.parent / "local-agent-mode-sessions"
        if local_agent_root.exists():
            for config_path in local_agent_root.rglob(".claude.json"):
                _merge_email_from_claude_config(emails, config_path)
    return emails


def _merge_email_from_claude_config(emails: dict[str, str], config_path: Path) -> None:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    account = data.get("oauthAccount")
    if not isinstance(account, dict):
        return
    account_uuid = account.get("accountUuid")
    email = account.get("emailAddress")
    if (
        isinstance(account_uuid, str)
        and account_uuid
        and isinstance(email, str)
        and email.strip()
    ):
        emails.setdefault(account_uuid, email.strip())


def gateway_server_url(claude_root: Path) -> str | None:
    """Gateway base URL for 3p deployments.

    Returns None for regular claude.ai installs, the server URL for gateway
    installs, and "" for a gateway whose URL could not be determined.
    """
    try:
        config = json.loads(
            (claude_root / "claude_desktop_config.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict) or config.get("deploymentMode") != "3p":
        return None
    # Prefer the most recently modified creds file: a reconfigured gateway
    # leaves the old host-creds-*.json behind, and lexicographic order would
    # pick the stale one.
    creds_files = sorted(
        claude_root.glob("host-creds-*.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for creds_path in creds_files:
        try:
            data = json.loads(creds_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        env = data.get("env")
        if isinstance(env, dict):
            url = env.get("ANTHROPIC_BASE_URL")
            if isinstance(url, str) and url.strip():
                return url.strip()
    return ""
