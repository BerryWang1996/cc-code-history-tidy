from tests.fixtures import build_claude_fixture
from cc_history_tidy.paths import discover_claude_environment


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
