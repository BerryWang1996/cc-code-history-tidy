import json

from cc_history_tidy import gui
from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.paths import discover_claude_environment
from cc_history_tidy.backup import create_backup
from cc_history_tidy.account_config import (
    AccountDisplay,
    AccountLabelConfig,
    save_account_label_config,
)
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


def test_main_window_constructs():
    app = create_app([])
    window = MainWindow()

    assert app is not None
    assert window.windowTitle()


def test_main_window_loads_scanned_accounts(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow()

    window.load_environment(env)

    assert window.session_tree.topLevelItemCount() == 2


def test_main_window_uses_account_label_config(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    config_path = tmp_path / "account-groups.json"
    save_account_label_config(
        AccountLabelConfig(
            accounts={
                fixture.source_account_uuid: AccountDisplay(label="Old Work"),
            }
        ),
        config_path,
    )
    create_app([])
    window = MainWindow(account_config_path=config_path)

    window.load_environment(env)

    source_account = _find_item_by_data(window.session_tree, fixture.source_account_uuid)
    assert source_account.text(0) == "Old Work"
    assert source_account.child(0).text(0) == "Archive Code Group"


def test_main_window_places_unassigned_sessions_under_ungrouped(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow()

    window.load_environment(env)

    ungrouped_group = _find_item_by_data(window.session_tree, "ungrouped")
    assert ungrouped_group.text(0) == "Ungrouped"
    assert ungrouped_group.child(0).text(0) == "Ungrouped session"


def test_tree_normalizes_session_dropped_on_ungrouped_session(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    _write_extra_unassigned_session(fixture, "desktop-ungrouped-2", "Second ungrouped")
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow()
    window.load_environment(env)
    ungrouped_group = _find_item_by_data(window.session_tree, "ungrouped")
    first_session = ungrouped_group.child(0)
    second_session = ungrouped_group.child(1)

    moved = ungrouped_group.takeChild(ungrouped_group.indexOfChild(first_session))
    second_session.addChild(moved)
    window.session_tree.normalize_structure()

    assert ungrouped_group.childCount() == 2
    assert second_session.childCount() == 0
    assert moved.parent() == ungrouped_group


def test_tree_normalizes_group_dropped_inside_group_to_account_sibling(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow()
    window.load_environment(env)
    current_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    ungrouped_group = _find_item_by_data(window.session_tree, "ungrouped")
    account_item = current_group.parent()

    moved = account_item.takeChild(account_item.indexOfChild(ungrouped_group))
    current_group.addChild(moved)
    window.session_tree.normalize_structure()

    assert moved.parent() == account_item
    assert current_group.childCount() == 1


def test_tree_drops_session_on_account_into_created_ungrouped_group(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow()
    window.load_environment(env)
    source_account = _find_item_by_data(window.session_tree, fixture.source_account_uuid)
    original_ungrouped = _find_item_by_data(window.session_tree, "ungrouped")
    session_item = original_ungrouped.child(0)

    moved = window.session_tree.move_items_to_target([session_item], source_account, None)

    target_ungrouped = _direct_child_by_data(source_account, "ungrouped")
    assert moved
    assert target_ungrouped is not None
    assert session_item.parent() == target_ungrouped


def test_main_window_stages_session_move_without_writing(tmp_path):
    fixture = build_claude_fixture(tmp_path)
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
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    source_session = source_group.child(0)

    moved = source_group.takeChild(source_group.indexOfChild(source_session))
    target_group.addChild(moved)

    planned = window.planned_session_moves()

    assert len(planned) == 1
    assert not (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    ).exists()


def test_main_window_executes_staged_session_move(tmp_path):
    fixture = build_claude_fixture(tmp_path)
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
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    source_session = source_group.child(0)
    moved = source_group.takeChild(source_group.indexOfChild(source_session))
    target_group.addChild(moved)

    window.execute_plan()

    assert (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    ).exists()
    assert not (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    ).exists()


def test_copy_paste_keeps_source_and_creates_copy(tmp_path):
    fixture = build_claude_fixture(tmp_path)
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
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    window.session_tree.setCurrentItem(source_group.child(0))
    window.session_tree.copy_selected_sessions()
    window.session_tree.paste_to(target_group)

    window.execute_plan()

    assert (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    ).exists()
    target_dir = fixture.sessions_root / fixture.current_account_uuid / fixture.current_group_id
    copied_ids = {
        json.loads(path.read_text(encoding="utf-8"))["sessionId"]
        for path in target_dir.glob("*.json")
    }
    assert "desktop-source" not in copied_ids
    assert len(copied_ids - {"desktop-current", "desktop-ungrouped"}) == 1


def test_main_window_copies_between_different_session_roots(tmp_path):
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
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)
    window.load_environment(env)
    source_group = _find_item_by_data(window.session_tree, fixture.source_code_group_id)
    gateway_account = _find_item_by_data(window.session_tree, gateway_account_uuid)
    window.session_tree.setCurrentItem(source_group.child(0))
    window.session_tree.copy_selected_sessions()
    window.session_tree.paste_to(gateway_account)

    window.execute_plan()

    # the source stays; a fresh-id copy lands in the gateway root
    assert (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    ).exists()
    gateway_ids = {
        json.loads(path.read_text(encoding="utf-8"))["sessionId"]
        for path in (gateway_sessions_root / gateway_account_uuid).rglob("*.json")
    }
    assert "desktop-source" not in gateway_ids
    assert len(gateway_ids - {"gateway-session"}) == 1


def test_execute_rolls_back_files_when_config_write_fails(tmp_path, monkeypatch):
    fixture = build_claude_fixture(tmp_path)
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
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    source_session = source_group.child(0)
    moved = source_group.takeChild(source_group.indexOfChild(source_session))
    target_group.addChild(moved)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )
    target_file = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    )

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("config write failed")

    monkeypatch.setattr(gui, "save_code_group_layout_to_desktop_config", fail_write)

    window.execute_plan()

    assert source_file.exists()
    assert not target_file.exists()
    assert "已全部回滚" in window.status_label.text()


def test_main_window_executes_code_group_only_move_without_filesystem_move(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)
    window.load_environment(env)
    ungrouped_group = _find_item_by_data(window.session_tree, "ungrouped")
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    source_session = ungrouped_group.child(0)
    moved = ungrouped_group.takeChild(ungrouped_group.indexOfChild(source_session))
    target_group.addChild(moved)
    source_file = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-ungrouped.json"
    )

    window.execute_plan()

    config = json.loads((fixture.sessions_root.parent / "claude_desktop_config.json").read_text())
    dframe_slice = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    assert source_file.exists()
    assert dframe_slice["customGroupAssignments"]["code:desktop-ungrouped"] == fixture.current_code_group_id
    assert "code:desktop-ungrouped" in dframe_slice["customGroupOrder"][fixture.current_code_group_id]


def test_dry_run_reports_layout_only_changes(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(backup_parent=tmp_path / "backups", process_checker=lambda: False,
        execute_confirmer=lambda summary: True)
    window.load_environment(env)
    ungrouped_group = _find_item_by_data(window.session_tree, "ungrouped")
    target_group = _find_item_by_data(window.session_tree, fixture.current_code_group_id)
    source_session = ungrouped_group.child(0)
    moved = ungrouped_group.takeChild(ungrouped_group.indexOfChild(source_session))
    target_group.addChild(moved)

    window.show_dry_run()

    assert "0 个移动、0 个复制" in window.status_label.text()
    assert "布局更新：yes" in window.status_label.text()


def test_execute_button_disabled_when_claude_is_running(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )
    create_app([])
    window = MainWindow(process_checker=lambda: True)

    window.load_environment(env)

    assert not window.execute_button.isEnabled()
    assert "关闭 Claude" in window.execute_button.toolTip()


def test_main_window_lists_available_backups(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    backup_parent = tmp_path / "backups"
    create_backup(fixture.sessions_root, backup_parent, reason="unit-test")
    create_app([])
    window = MainWindow(backup_parent=backup_parent)

    assert len(window.available_backups()) == 1


def _write_extra_unassigned_session(fixture, session_id: str, title: str) -> None:
    path = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / f"{session_id}.json"
    )
    path.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "cliSessionId": f"cli-{session_id}",
                "title": title,
                "cwd": "C:/Work/project",
                "createdAt": 1,
                "lastActivityAt": 1,
                "isArchived": False,
            }
        ),
        encoding="utf-8",
    )


def _direct_child_by_data(item, value):
    for index in range(item.childCount()):
        child = item.child(index)
        if child.data(0, 256) == value:
            return child
    return None
