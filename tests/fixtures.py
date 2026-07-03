from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ClaudeFixture:
    user_profile: Path
    appdata: Path
    localappdata: Path
    sessions_root: Path
    current_account_uuid: str
    source_account_uuid: str
    current_group_id: str
    source_group_id: str
    current_code_group_id: str
    source_code_group_id: str
    ungrouped_session_id: str


def build_claude_fixture(tmp_path: Path) -> ClaudeFixture:
    user_profile = tmp_path / "Users" / "example"
    appdata = user_profile / "AppData" / "Roaming"
    localappdata = user_profile / "AppData" / "Local"
    current_account_uuid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    source_account_uuid = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    current_group_id = "11111111-1111-4111-8111-111111111111"
    source_group_id = "22222222-2222-4222-8222-222222222222"
    current_code_group_id = "cg-current"
    source_code_group_id = "cg-source"
    ungrouped_session_id = "desktop-ungrouped"

    claude_dir = user_profile / ".claude"
    transcript_root = claude_dir / "projects"
    project_dir = transcript_root / "C--Work-project"
    project_dir.mkdir(parents=True)
    (project_dir / "cli-current.jsonl").write_text(
        '{"type":"user","sessionId":"cli-current","message":{"content":"current"}}\n',
        encoding="utf-8",
    )
    (project_dir / "cli-source.jsonl").write_text(
        '{"type":"user","sessionId":"cli-source","message":{"content":"source"}}\n',
        encoding="utf-8",
    )
    (project_dir / "cli-ungrouped.jsonl").write_text(
        '{"type":"user","sessionId":"cli-ungrouped","message":{"content":"ungrouped"}}\n',
        encoding="utf-8",
    )

    claude_dir.mkdir(exist_ok=True)
    (user_profile / ".claude.json").write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "accountUuid": current_account_uuid,
                    "organizationUuid": current_group_id,
                    "organizationName": "Current Workspace",
                    "displayName": "Current User",
                    "emailAddress": "current@example.com",
                }
            }
        ),
        encoding="utf-8",
    )

    desktop_root = (
        localappdata
        / "Packages"
        / "Claude_pzs8sxrjxfjjc"
        / "LocalCache"
        / "Roaming"
        / "Claude"
    )
    sessions_root = desktop_root / "claude-code-sessions"
    current_dir = sessions_root / current_account_uuid / current_group_id
    source_dir = sessions_root / source_account_uuid / source_group_id
    current_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)

    _write_session(current_dir / "session-current.json", "desktop-current", "cli-current", "Current session")
    _write_session(
        current_dir / "session-ungrouped.json",
        ungrouped_session_id,
        "cli-ungrouped",
        "Ungrouped session",
    )
    _write_session(source_dir / "session-source.json", "desktop-source", "cli-source", "Source session")

    (desktop_root / "claude_desktop_config.json").write_text(
        json.dumps(
            {
                "preferences": {
                    "epitaxyPrefs": {
                        "dframe-local-slice": {
                            "customGroups": [
                                {"id": current_code_group_id, "name": "Current Code Group"},
                                {"id": source_code_group_id, "name": "Archive Code Group"},
                            ],
                            "customGroupAssignments": {
                                "code:desktop-current": current_code_group_id,
                                "code:desktop-source": source_code_group_id,
                            },
                            "customGroupOrder": {
                                current_code_group_id: ["code:desktop-current"],
                                source_code_group_id: ["code:desktop-source"],
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    old_agent_config = (
        desktop_root
        / "local-agent-mode-sessions"
        / source_account_uuid
        / source_group_id
        / "local-example"
        / ".claude"
    )
    old_agent_config.mkdir(parents=True)
    (old_agent_config / ".claude.json").write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "accountUuid": source_account_uuid,
                    "organizationUuid": source_group_id,
                    "organizationName": "Archive Workspace",
                    "displayName": "Archive User",
                    "emailAddress": "archive@example.com",
                }
            }
        ),
        encoding="utf-8",
    )

    return ClaudeFixture(
        user_profile=user_profile,
        appdata=appdata,
        localappdata=localappdata,
        sessions_root=sessions_root,
        current_account_uuid=current_account_uuid,
        source_account_uuid=source_account_uuid,
        current_group_id=current_group_id,
        source_group_id=source_group_id,
        current_code_group_id=current_code_group_id,
        source_code_group_id=source_code_group_id,
        ungrouped_session_id=ungrouped_session_id,
    )


def _write_session(path: Path, session_id: str, cli_session_id: str, title: str) -> None:
    path.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "cliSessionId": cli_session_id,
                "title": title,
                "cwd": "C:/Work/project",
                "createdAt": 1,
                "lastActivityAt": 2,
                "isArchived": False,
            }
        ),
        encoding="utf-8",
    )
