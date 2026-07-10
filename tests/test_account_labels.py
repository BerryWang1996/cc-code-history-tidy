import json

from cc_history_tidy.account_config import (
    AccountDisplay,
    AccountLabelConfig,
    save_account_label_config,
)
from cc_history_tidy.account_identity import gateway_server_url
from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def _find_account_item(tree, account_uuid):
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.data(0, 256) == account_uuid:
            return item
    raise AssertionError(f"Account {account_uuid!r} not found")


def _make_gateway_root(fixture, account_uuid, group_id, url="https://gw.example.com"):
    gateway_root = fixture.localappdata / "Claude-3p"
    sessions_root = gateway_root / "claude-code-sessions"
    account_dir = sessions_root / account_uuid / group_id
    account_dir.mkdir(parents=True)
    (account_dir / "gw-session.json").write_text(
        json.dumps(
            {
                "sessionId": "gw-session",
                "cliSessionId": "cli-gw",
                "title": "Gateway session",
                "cwd": "C:/Work/gw",
                "createdAt": 1,
                "lastActivityAt": 2,
                "isArchived": False,
            }
        ),
        encoding="utf-8",
    )
    (gateway_root / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": account_uuid}), encoding="utf-8"
    )
    (gateway_root / "claude_desktop_config.json").write_text(
        json.dumps({"deploymentMode": "3p"}), encoding="utf-8"
    )
    if url is not None:
        (gateway_root / "host-creds-abc.json").write_text(
            json.dumps({"env": {"ANTHROPIC_BASE_URL": url, "ANTHROPIC_AUTH_TOKEN": "x"}}),
            encoding="utf-8",
        )
    return gateway_root


def _window(tmp_path, fixture, **kwargs):
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        **kwargs,
    )
    window.load_environment(env)
    return window


def test_accounts_show_emails_when_discoverable(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    window = _window(tmp_path, fixture)

    current = _find_account_item(window.session_tree, fixture.current_account_uuid)
    source = _find_account_item(window.session_tree, fixture.source_account_uuid)

    # from ~/.claude.json and local-agent-mode-sessions respectively
    assert current.text(0) == "current@example.com"
    assert source.text(0) == "archive@example.com"


def test_configured_label_beats_email(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    config_path = tmp_path / "account-groups.json"
    save_account_label_config(
        AccountLabelConfig(
            accounts={fixture.current_account_uuid: AccountDisplay(label="My Main")}
        ),
        config_path,
    )
    window = _window(tmp_path, fixture, account_config_path=config_path)

    current = _find_account_item(window.session_tree, fixture.current_account_uuid)
    assert current.text(0) == "My Main"


def test_gateway_account_shows_server_url(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gw_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    _make_gateway_root(fixture, gw_uuid, fixture.current_group_id)
    window = _window(tmp_path, fixture)

    gw_item = _find_account_item(window.session_tree, gw_uuid)
    assert "[https://gw.example.com]" in gw_item.text(0)
    # non-gateway accounts have no gateway suffix
    current = _find_account_item(window.session_tree, fixture.current_account_uuid)
    assert "gateway" not in current.text(0) and "[https://" not in current.text(0)


def test_gateway_without_url_gets_generic_tag(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gw_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    _make_gateway_root(fixture, gw_uuid, fixture.current_group_id, url=None)
    window = _window(tmp_path, fixture)

    gw_item = _find_account_item(window.session_tree, gw_uuid)
    assert "[gateway]" in gw_item.text(0)


def test_gateway_server_url_detection(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gw_root = _make_gateway_root(
        fixture, "f7ec41bb-c6ae-4053-b2cf-334cd4c46726", fixture.current_group_id
    )

    assert gateway_server_url(gw_root) == "https://gw.example.com"
    # a regular claude.ai root is not a gateway
    assert gateway_server_url(fixture.sessions_root.parent) is None


def test_gateway_server_url_prefers_newest_creds(tmp_path):
    import os
    import time as _time
    from cc_history_tidy.account_identity import gateway_server_url

    root = tmp_path / "Claude-3p"
    root.mkdir()
    (root / "claude_desktop_config.json").write_text(
        __import__("json").dumps({"deploymentMode": "3p"}), encoding="utf-8"
    )
    old = root / "host-creds-2024-01.json"
    new = root / "host-creds-2024-06.json"
    old.write_text(
        __import__("json").dumps({"env": {"ANTHROPIC_BASE_URL": "https://old-gw"}}),
        encoding="utf-8",
    )
    new.write_text(
        __import__("json").dumps({"env": {"ANTHROPIC_BASE_URL": "https://new-gw"}}),
        encoding="utf-8",
    )
    # make the lexicographically-earlier file the NEWER one to prove mtime wins
    now = _time.time()
    os.utime(new, (now - 100, now - 100))
    os.utime(old, (now, now))

    assert gateway_server_url(root) == "https://old-gw"
