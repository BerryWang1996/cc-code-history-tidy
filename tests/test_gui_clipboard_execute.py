import json

from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.models import MigrationMode
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def _load_window(tmp_path, **kwargs):
    fixture = build_claude_fixture(tmp_path)
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        execute_confirmer=kwargs.pop("execute_confirmer", lambda summary: True),
        **kwargs,
    )
    window.load_environment(env)
    return fixture, window


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


def test_cut_paste_plans_move_and_copy_paste_plans_copy(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)

    current_ungrouped_session = _find_item_by_data(tree, "ungrouped").child(0)
    tree.setCurrentItem(current_ungrouped_session)
    # copy a current-account session into the SOURCE account
    tree.copy_selected_sessions()
    source_account = _find_item_by_data(tree, fixture.source_account_uuid)
    tree.paste_to(source_account)

    planned = window.planned_session_moves()
    modes = sorted(move.mode.value for move in planned)
    assert modes == ["copy", "move"]


def test_execute_mixed_copy_and_move(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    # MOVE session-source into the current account
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    # COPY session-current into the source account
    current_session_item = _find_item_by_data(tree, fixture.current_code_group_id).child(0)
    tree.setCurrentItem(current_session_item)
    tree.copy_selected_sessions()
    tree.paste_to(_find_item_by_data(tree, fixture.source_account_uuid))

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
    # the copy landed in the source account with a fresh session id
    source_account_dir = fixture.sessions_root / fixture.source_account_uuid
    copied_ids = {
        json.loads(p.read_text(encoding="utf-8"))["sessionId"]
        for p in source_account_dir.rglob("*.json")
    }
    assert "desktop-current" not in copied_ids
    assert len(copied_ids) == 1


def test_execute_confirmer_cancel_leaves_disk_untouched(tmp_path):
    fixture, window = _load_window(tmp_path, execute_confirmer=lambda summary: False)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )

    window.execute_plan()

    assert source_file.exists()
    assert not (tmp_path / "backups").exists()
    assert "取消" in window.status_label.text()


def test_ghost_copy_does_not_pollute_staged_layout(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)

    visible_keys, by_root = window.staged_code_group_layout_by_root()
    assignments, _order = by_root[fixture.sessions_root]
    # the original keeps its group; the ghost adds nothing
    assert assignments["code:desktop-source"] == fixture.source_code_group_id

    window.execute_plan()

    config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    slice_data = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    assert slice_data["customGroupAssignments"]["code:desktop-source"] == fixture.source_code_group_id


def test_copied_session_lands_in_pasted_group_after_execute(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)

    window.execute_plan()

    config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    slice_data = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    order = slice_data["customGroupOrder"][fixture.current_code_group_id]
    new_keys = [key for key in order if key != "code:desktop-current"]
    assert len(new_keys) == 1  # the copy's NEW id was assigned to the pasted group
    assert slice_data["customGroupAssignments"][new_keys[0]] == fixture.current_code_group_id
    # and it is not the old id
    assert new_keys[0] != "code:desktop-source"


def test_copied_group_lands_all_sessions_in_group_after_execute(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    tree.setCurrentItem(source_group)
    tree.copy_selected_sessions()
    tree.paste_to(current_account)

    window.execute_plan()

    config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    slice_data = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    order = slice_data["customGroupOrder"][fixture.source_code_group_id]
    # original assignment plus the fresh copy id
    assert "code:desktop-source" in order
    assert len(order) == 2
    # the group label was persisted alongside
    labels = {group["id"]: group["name"] for group in slice_data.get("customGroups", [])}
    assert labels.get(fixture.source_code_group_id) == "Archive Code Group"


def test_language_combo_switches_ui_and_persists(tmp_path):
    fixture, window = _load_window(tmp_path, settings_path=tmp_path / "settings.json")
    from cc_history_tidy import i18n

    index = window.language_combo.findData("en")
    window.language_combo.setCurrentIndex(index)

    assert i18n.current_language() == "en"
    assert window.scan_button.text() == i18n.LANGS["en"]["btn.scan"]
    assert window.session_tree.headerItem().text(1) == i18n.LANGS["en"]["header.updated"]
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["language"] == "en"

    back = window.language_combo.findData("zh")
    window.language_combo.setCurrentIndex(back)
    assert i18n.current_language() == "zh"
