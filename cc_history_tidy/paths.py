from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class ClaudeEnvironment:
    user_profile: Path
    appdata: Path
    localappdata: Path
    claude_config: Path
    transcript_root: Path
    sessions_root: Path
    sessions_roots: tuple[Path, ...]
    current_account_uuid: str


def discover_claude_environment(
    user_profile: Path | None = None,
    appdata: Path | None = None,
    localappdata: Path | None = None,
) -> ClaudeEnvironment:
    user_profile = Path(user_profile or os.environ["USERPROFILE"])
    appdata = Path(appdata or os.environ["APPDATA"])
    localappdata = Path(localappdata or os.environ["LOCALAPPDATA"])

    claude_config = user_profile / ".claude.json"
    current_account_uuid = _read_current_account_uuid(claude_config)
    transcript_root = user_profile / ".claude" / "projects"
    candidate_roots = _candidate_sessions_roots(appdata, localappdata)
    sessions_root, current_account_uuid = _select_sessions_root(candidate_roots, current_account_uuid)
    sessions_roots = _ordered_sessions_roots(candidate_roots, sessions_root)

    return ClaudeEnvironment(
        user_profile=user_profile,
        appdata=appdata,
        localappdata=localappdata,
        claude_config=claude_config,
        transcript_root=transcript_root,
        sessions_root=sessions_root,
        sessions_roots=sessions_roots,
        current_account_uuid=current_account_uuid,
    )


def _read_current_account_uuid(config_path: Path) -> str:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Claude config not found: {config_path}") from exc
    account_uuid = data.get("oauthAccount", {}).get("accountUuid")
    if not account_uuid:
        raise ValueError(f"Claude config does not contain oauthAccount.accountUuid: {config_path}")
    return account_uuid


def _candidate_sessions_roots(appdata: Path, localappdata: Path) -> list[Path]:
    roots: list[Path] = []
    candidate_claude_roots = [
        appdata / "Claude",
        localappdata / "Claude",
        localappdata / "Claude-3p",
    ]

    packages = localappdata / "Packages"
    if packages.exists():
        for package_dir in packages.glob("Claude_*"):
            candidate_claude_roots.append(package_dir / "LocalCache" / "Roaming" / "Claude")

    for root in candidate_claude_roots:
        sessions_root = root / "claude-code-sessions"
        if sessions_root.exists():
            roots.append(sessions_root)
    return roots


def _read_root_current_account_uuid(claude_root: Path) -> str | None:
    config_path = claude_root / "config.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    account_uuid = data.get("lastKnownAccountUuid")
    return account_uuid if isinstance(account_uuid, str) and account_uuid else None


def _select_sessions_root(candidates: list[Path], current_account_uuid: str) -> tuple[Path, str]:
    if not candidates:
        raise FileNotFoundError("No claude-code-sessions directory found")
    root_account_candidates = []
    for root in candidates:
        root_account_uuid = _read_root_current_account_uuid(root.parent)
        if root_account_uuid and (root / root_account_uuid).exists():
            root_account_candidates.append((root, root_account_uuid))
    if root_account_candidates:
        return max(root_account_candidates, key=lambda item: item[0].stat().st_mtime)

    containing_current = [
        root for root in candidates if (root / current_account_uuid).exists()
    ]
    if containing_current:
        return max(containing_current, key=lambda path: path.stat().st_mtime), current_account_uuid
    selected = max(candidates, key=lambda path: path.stat().st_mtime)
    account_dirs = [path for path in selected.iterdir() if path.is_dir()]
    if len(account_dirs) == 1:
        return selected, account_dirs[0].name
    return selected, current_account_uuid


def _ordered_sessions_roots(candidates: list[Path], selected: Path) -> tuple[Path, ...]:
    remaining = [root for root in candidates if root != selected]
    remaining.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return (selected, *remaining)
