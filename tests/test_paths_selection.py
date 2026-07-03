import json

import pytest

from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def test_discover_prefers_root_matching_claude_json_account(tmp_path):
    """A newer foreign root must not shadow the install the user is logged into."""
    fixture = build_claude_fixture(tmp_path)
    # The daily-driver root declares the same account as ~/.claude.json.
    (fixture.sessions_root.parent / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": fixture.current_account_uuid}),
        encoding="utf-8",
    )
    # A gateway root installed later (newer mtime) with a different account.
    gateway_account_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    gateway_root = fixture.localappdata / "Claude-3p"
    gateway_sessions_root = gateway_root / "claude-code-sessions"
    (gateway_sessions_root / gateway_account_uuid).mkdir(parents=True)
    (gateway_root / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": gateway_account_uuid}),
        encoding="utf-8",
    )

    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )

    assert env.sessions_root == fixture.sessions_root
    assert env.current_account_uuid == fixture.current_account_uuid


def test_discover_tolerates_missing_claude_json(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    (fixture.user_profile / ".claude.json").unlink()
    gateway_account_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    gateway_root = fixture.localappdata / "Claude-3p"
    gateway_sessions_root = gateway_root / "claude-code-sessions"
    (gateway_sessions_root / gateway_account_uuid).mkdir(parents=True)
    (gateway_root / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": gateway_account_uuid}),
        encoding="utf-8",
    )

    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )

    assert env.current_account_uuid == gateway_account_uuid
    assert env.sessions_root == gateway_sessions_root


def test_discover_fails_clearly_when_no_account_identifiable(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    (fixture.user_profile / ".claude.json").unlink()
    # Two account dirs, no config.json anywhere: the account is ambiguous.
    extra_account = fixture.sessions_root / "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    extra_account.mkdir()

    with pytest.raises(ValueError, match="current Claude account"):
        discover_claude_environment(
            fixture.user_profile,
            fixture.appdata,
            fixture.localappdata,
        )
