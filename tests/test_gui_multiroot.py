import json

from cc_history_tidy import gui
from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def _find_item_by_data(root, value):
    for index in range(root.topLevelItemCount()):
        found = _find_child_by_data(root.topLevelItem(index), value)
        if found is not None:
            return found
    raise AssertionError(f"Item with data {value!r} not found")


def _find_child_by_data(item, value):
    if item.data(0, 256) == value:
        return item
    for index in range(item.childCount()):
        found = _find_child_by_data(item.child(index), value)
        if found is not None:
            return found
    return None


def _direct_child_by_data(item, value):
    for index in range(item.childCount()):
        child = item.child(index)
        if child.data(0, 256) == value:
            return child
    return None


def _write_session_at(path, session_id, cli_session_id, title):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _build_gateway_root(fixture, account_uuid, group_id):
    gateway_root = fixture.localappdata / "Claude-3p"
    gateway_sessions_root = gateway_root / "claude-code-sessions"
    (gateway_sessions_root / account_uuid / group_id).mkdir(parents=True)
    (gateway_root / "config.json").write_text(
        json.dumps({"lastKnownAccountUuid": account_uuid}),
        encoding="utf-8",
    )
    return gateway_sessions_root


def test_scan_of_multi_org_account_plans_no_moves(tmp_path):
    """A code group spanning two org dirs must not trigger unstaged file moves."""
    fixture = build_claude_fixture(tmp_path)
    second_org = "99999999-9999-4999-8999-999999999999"
    _write_session_at(
        fixture.sessions_root / fixture.current_account_uuid / second_org / "session-multiorg.json",
        "desktop-multiorg",
        "cli-multiorg",
        "Multi-org session",
    )
    config_path = fixture.sessions_root.parent / "claude_desktop_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    dframe_slice = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    dframe_slice["customGroupAssignments"]["code:desktop-multiorg"] = fixture.current_code_group_id
    dframe_slice["customGroupOrder"][fixture.current_code_group_id].append("code:desktop-multiorg")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)

    window.load_environment(env)

    assert window.planned_session_moves() == []
    assert window.tree_signature() == window._loaded_tree_signature


def test_moving_session_between_same_account_roots_plans_move(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gateway_sessions_root = _build_gateway_root(
        fixture, fixture.current_account_uuid, fixture.current_group_id
    )
    _write_session_at(
        gateway_sessions_root / fixture.current_account_uuid / fixture.current_group_id / "session-gw.json",
        "desktop-gw",
        "cli-gw",
        "Gateway session",
    )
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)
    window.load_environment(env)

    account_items = [
        window.session_tree.topLevelItem(index)
        for index in range(window.session_tree.topLevelItemCount())
        if window.session_tree.topLevelItem(index).data(0, 256) == fixture.current_account_uuid
    ]
    assert len(account_items) == 2
    by_root = {item.data(0, 256 + 2): item for item in account_items}
    msix_item = by_root[fixture.sessions_root]
    gateway_item = by_root[gateway_sessions_root]
    assert msix_item.text(0) != gateway_item.text(0)

    source_group = _direct_child_by_data(msix_item, fixture.current_code_group_id)
    target_group = _direct_child_by_data(gateway_item, "ungrouped")
    source_session = source_group.child(0)
    moved = source_group.takeChild(source_group.indexOfChild(source_session))
    target_group.addChild(moved)

    planned = window.planned_session_moves()
    assert len(planned) == 1
    assert planned[0].target_sessions_root == gateway_sessions_root

    window.execute_plan()

    assert (
        gateway_sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-current.json"
    ).exists()
    assert not (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-current.json"
    ).exists()


def test_failed_cross_root_execute_rolls_back_every_root(tmp_path, monkeypatch):
    fixture = build_claude_fixture(tmp_path)
    gateway_account_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    gateway_sessions_root = _build_gateway_root(fixture, gateway_account_uuid, fixture.current_group_id)
    _write_session_at(
        gateway_sessions_root / gateway_account_uuid / fixture.current_group_id / "gateway-session.json",
        "gateway-session",
        "cli-gateway",
        "Gateway session",
    )
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)
    window.load_environment(env)
    source_group = _find_item_by_data(window.session_tree, fixture.source_code_group_id)
    gateway_account = _find_item_by_data(window.session_tree, gateway_account_uuid)
    gateway_ungrouped = _direct_child_by_data(gateway_account, "ungrouped")
    source_session = source_group.child(0)
    moved = source_group.takeChild(source_group.indexOfChild(source_session))
    gateway_ungrouped.addChild(moved)

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("config write failed")

    monkeypatch.setattr(gui, "save_code_group_layout_to_desktop_config", fail_write)

    window.execute_plan()

    # The MOVE into the gateway root already happened before the failure;
    # rollback must undo BOTH roots, not just the primary one.
    assert (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    ).exists()
    assert not (
        gateway_sessions_root
        / gateway_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    ).exists()
    assert "已全部回滚" in window.status_label.text()


def test_layout_written_to_each_involved_root(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    gateway_account_uuid = "f7ec41bb-c6ae-4053-b2cf-334cd4c46726"
    gateway_sessions_root = _build_gateway_root(fixture, gateway_account_uuid, fixture.current_group_id)
    gateway_root = gateway_sessions_root.parent
    _write_session_at(
        gateway_sessions_root / gateway_account_uuid / fixture.current_group_id / "gateway-session.json",
        "gateway-session",
        "cli-gateway",
        "Gateway session",
    )
    (gateway_root / "claude_desktop_config.json").write_text(
        json.dumps(
            {
                "preferences": {
                    "epitaxyPrefs": {
                        "dframe-local-slice": {
                            "customGroups": [{"id": "cg-gateway", "name": "Gateway Group"}],
                            "customGroupAssignments": {"code:gateway-session": "cg-gateway"},
                            "customGroupOrder": {"cg-gateway": ["code:gateway-session"]},
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)
    window.load_environment(env)
    source_group = _find_item_by_data(window.session_tree, fixture.source_code_group_id)
    gateway_group = _find_item_by_data(window.session_tree, "cg-gateway")
    source_session = source_group.child(0)
    moved = source_group.takeChild(source_group.indexOfChild(source_session))
    gateway_group.addChild(moved)

    window.execute_plan()

    gateway_config = json.loads(
        (gateway_root / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    gateway_slice = gateway_config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    # The moved session's group assignment must land in the GATEWAY root's
    # config (where the session now lives), not only in the primary root's.
    assert gateway_slice["customGroupAssignments"]["code:desktop-source"] == "cg-gateway"
    assert "code:desktop-source" in gateway_slice["customGroupOrder"]["cg-gateway"]

    primary_config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    primary_slice = primary_config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    # And the stale assignment must be purged from the old root's config.
    assert "code:desktop-source" not in primary_slice.get("customGroupAssignments", {})
