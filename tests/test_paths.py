from tests.fixtures import build_claude_fixture
from cc_history_tidy.paths import discover_claude_environment
import json


def test_discover_environment_from_fixture(tmp_path):
    fixture = build_claude_fixture(tmp_path)

    env = discover_claude_environment(
        user_profile=fixture.user_profile,
        appdata=fixture.appdata,
        localappdata=fixture.localappdata,
    )

    assert env.current_account_uuid == fixture.current_account_uuid
    assert env.transcript_root == fixture.user_profile / ".claude" / "projects"
    assert env.sessions_root == fixture.sessions_root


def test_discover_prefers_gateway_root_current_account(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gateway_account_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    gateway_root = fixture.localappdata / "Claude-3p"
    gateway_sessions_root = gateway_root / "claude-code-sessions"
    (gateway_sessions_root / gateway_account_uuid).mkdir(parents=True)
    (gateway_root / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": gateway_account_uuid}),
        encoding="utf-8",
    )

    env = discover_claude_environment(
        user_profile=fixture.user_profile,
        appdata=fixture.appdata,
        localappdata=fixture.localappdata,
    )

    assert env.current_account_uuid == gateway_account_uuid
    assert env.sessions_root == gateway_sessions_root
    assert env.sessions_roots == (gateway_sessions_root, fixture.sessions_root)
