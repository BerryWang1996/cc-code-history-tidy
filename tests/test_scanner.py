from tests.fixtures import build_claude_fixture
from cc_history_tidy.paths import discover_claude_environment
from cc_history_tidy.scanner import scan_accounts
import json


def test_scanner_lists_current_and_source_sessions(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )

    accounts = scan_accounts(env)

    assert len(accounts) == 2
    sessions = [session for account in accounts for session in account.sessions]
    assert {session.cli_session_id for session in sessions} == {
        "cli-current",
        "cli-source",
        "cli-ungrouped",
    }
    assert all(session.has_transcript for session in sessions)
    assert {session.group_id for session in sessions} == {
        fixture.current_group_id,
        fixture.source_group_id,
    }
    assert {session.code_group_id for session in sessions} == {
        fixture.current_code_group_id,
        fixture.source_code_group_id,
        "ungrouped",
    }
    assert {session.code_group_label for session in sessions} == {
        "Current Code Group",
        "Archive Code Group",
        "Ungrouped",
    }
    assert any(account.partition.is_current for account in accounts)


def test_scanner_preserves_code_group_order(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )

    accounts = scan_accounts(env)
    source = next(account for account in accounts if account.partition.account_uuid == fixture.source_account_uuid)

    assert source.sessions[0].code_group_id == fixture.source_code_group_id
    assert source.sessions[0].code_group_label == "Archive Code Group"


def test_scanner_lists_accounts_from_all_session_roots(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gateway_account_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    gateway_root = fixture.localappdata / "Claude-3p"
    gateway_sessions_root = gateway_root / "claude-code-sessions"
    gateway_account_dir = gateway_sessions_root / gateway_account_uuid / fixture.current_group_id
    gateway_account_dir.mkdir(parents=True)
    (gateway_root / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": gateway_account_uuid}),
        encoding="utf-8",
    )
    (gateway_account_dir / "gateway-session.json").write_text(
        json.dumps(
            {
                "sessionId": "gateway-session",
                "cliSessionId": "cli-gateway",
                "title": "Gateway session",
                "cwd": "C:/Work/gateway",
                "createdAt": 1,
                "lastActivityAt": 3,
                "isArchived": False,
            }
        ),
        encoding="utf-8",
    )
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )

    accounts = scan_accounts(env)

    assert {account.partition.account_uuid for account in accounts} == {
        fixture.current_account_uuid,
        fixture.source_account_uuid,
        gateway_account_uuid,
    }
    assert any(
        session.title == "Gateway session"
        for account in accounts
        for session in account.sessions
    )
