from cc_history_tidy.gui import MainWindow, create_app
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


def test_undo_restores_tree_after_paste(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    before = window.tree_signature()
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    assert window.tree_signature() != before

    assert tree.undo() is True
    assert window.tree_signature() == before
    assert window.planned_session_moves() == []


def test_redo_reapplies_undone_change(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    after = window.tree_signature()
    tree.undo()

    assert tree.redo() is True
    assert window.tree_signature() == after


def test_undo_on_empty_stack_returns_false(tmp_path):
    fixture, window = _load_window(tmp_path)
    assert window.session_tree.undo() is False


def test_reset_restores_initial_state_without_disk_rescan(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    initial = window.tree_signature()
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)

    window.reset_staged_changes()

    assert window.tree_signature() == initial
    assert tree.undo_stack == [] and tree.redo_stack == []
    assert tree.clipboard_mode is None


def test_undo_then_redo_preserves_ghost_items(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)
    with_ghost = window.tree_signature()

    tree.undo()
    tree.redo()

    assert window.tree_signature() == with_ghost
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    assert any(
        tree.is_ghost_item(target_group.child(i))
        for i in range(target_group.childCount())
    )


def test_undo_ghost_removal_brings_ghost_back(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.copy_selected_sessions()
    tree.paste_to(target_group)
    ghost = next(
        target_group.child(i)
        for i in range(target_group.childCount())
        if tree.is_ghost_item(target_group.child(i))
    )
    tree.remove_ghost_item(ghost)

    tree.undo()

    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    assert any(
        tree.is_ghost_item(target_group.child(i))
        for i in range(target_group.childCount())
    )
