from tests.fixtures import build_claude_fixture
from cc_history_tidy.paths import discover_claude_environment
from cc_history_tidy.scanner import scan_accounts


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
