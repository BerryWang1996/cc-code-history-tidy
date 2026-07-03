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


def _direct_child_by_data(item, value):
    for index in range(item.childCount()):
        child = item.child(index)
        if child.data(0, 256) == value:
            return child
    return None


def test_cut_group_paste_to_other_account_moves_whole_group(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)

    tree.setCurrentItem(source_group)
    assert tree.cut_selected_sessions() == 1
    assert tree.clipboard_kind == "group"
    assert tree.paste_to(current_account) >= 1

    assert source_group.parent() is current_account
    planned = window.planned_session_moves()
    assert len(planned) == 1
    assert planned[0].mode == MigrationMode.MOVE
    assert planned[0].target_account_uuid == fixture.current_account_uuid


def test_cut_group_merges_into_same_name_group(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_group = _find_item_by_data(tree, fixture.current_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    current_group.setText(0, source_group.text(0))  # same display name
    before_children = current_group.childCount()

    tree.setCurrentItem(source_group)
    tree.cut_selected_sessions()
    tree.paste_to(current_account)

    # merged: sessions joined the existing group, no duplicate group item
    assert current_group.childCount() == before_children + 1
    assert _direct_child_by_data(current_account, fixture.source_code_group_id) is None


def test_copy_group_creates_ghost_group(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)

    tree.setCurrentItem(source_group)
    tree.copy_selected_sessions()
    assert tree.paste_to(current_account) == 1

    # source untouched, ghost group under target with ghost sessions
    source_account = _find_item_by_data(tree, fixture.source_account_uuid)
    assert source_group.parent() is source_account
    ghost_group = _direct_child_by_data(current_account, fixture.source_code_group_id)
    assert ghost_group is not None
    assert tree.is_ghost_item(ghost_group)
    assert ghost_group.childCount() == 1
    assert tree.is_ghost_item(ghost_group.child(0))
    planned = window.planned_session_moves()
    assert [move.mode for move in planned] == [MigrationMode.COPY]


def test_copy_group_merges_ghosts_into_same_name_group(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_group = _find_item_by_data(tree, fixture.current_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    current_group.setText(0, source_group.text(0))
    before_children = current_group.childCount()

    tree.setCurrentItem(source_group)
    tree.copy_selected_sessions()
    tree.paste_to(current_account)

    assert current_group.childCount() == before_children + 1
    assert tree.is_ghost_item(current_group.child(current_group.childCount() - 1))
    # no new ghost group was created
    assert _direct_child_by_data(current_account, fixture.source_code_group_id) is None


def test_ungrouped_group_cannot_be_cut_or_copied(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    ungrouped = _find_item_by_data(tree, "ungrouped")
    tree.setCurrentItem(ungrouped)

    assert tree.cut_selected_sessions() == 0
    assert tree.copy_selected_sessions() == 0
    assert tree.clipboard_mode is None


def test_mixed_selection_is_rejected(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = source_group.child(0)
    source_group.setSelected(True)
    session_item.setSelected(True)

    assert tree.cut_selected_sessions() == 0
    assert tree.clipboard_mode is None


def test_drag_group_to_other_account_merges_same_name(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_group = _find_item_by_data(tree, fixture.current_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    current_group.setText(0, source_group.text(0))
    before_children = current_group.childCount()

    moved = tree.move_items_to_target([source_group], current_account, None)

    assert moved
    assert current_group.childCount() == before_children + 1
    assert _direct_child_by_data(current_account, fixture.source_code_group_id) is None


def test_undo_ghost_group_removes_whole_group(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    tree.setCurrentItem(source_group)
    tree.copy_selected_sessions()
    tree.paste_to(current_account)
    ghost_group = _direct_child_by_data(current_account, fixture.source_code_group_id)
    assert ghost_group is not None

    actions = dict(tree._context_actions_for(ghost_group))
    assert len(actions) == 1
    next(iter(actions.values()))()

    assert _direct_child_by_data(current_account, fixture.source_code_group_id) is None
