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


def test_noop_paste_back_to_origin_preserves_redo(tmp_path):
    # Regression: cut-then-paste-back-to-origin is a no-op and must NOT clear
    # the redo stack or add a spurious undo entry.
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    # 1) make a real change, then undo it -> a redo entry exists
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    assert tree.undo_stack and not tree.redo_stack
    tree.undo()
    assert tree.redo_stack, "undo should have produced a redo entry"
    redo_depth = len(tree.redo_stack)
    undo_depth = len(tree.undo_stack)

    # 2) a no-op paste (cut a session and paste back into its own group)
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    session = source_group.child(0)
    tree.setCurrentItem(session)
    tree.cut_selected_sessions()
    tree.paste_to(source_group)

    # the paste happened but changed nothing structurally
    assert session.parent() is source_group
    # redo history preserved, no spurious undo entry
    assert len(tree.redo_stack) == redo_depth
    assert len(tree.undo_stack) == undo_depth
    # and redo still works
    assert tree.redo() is True


def test_noop_drop_preserves_redo(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    tree.undo()
    redo_depth = len(tree.redo_stack)

    # dropping a session onto its own current group is a no-op structurally
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    session = source_group.child(0)
    tree.move_items_to_target([session], source_group, None)
    assert len(tree.redo_stack) == redo_depth


def test_session_count_role_survives_undo(tmp_path):
    from cc_history_tidy.tree_state import SESSION_COUNT_ROLE

    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    account = _find_item_by_data(tree, fixture.current_account_uuid)
    original = account.data(0, SESSION_COUNT_ROLE)
    assert isinstance(original, int)

    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    tree.setCurrentItem(source_group.child(0))
    tree.cut_selected_sessions()
    tree.paste_to(target_group)
    tree.undo()

    account = _find_item_by_data(tree, fixture.current_account_uuid)
    assert account.data(0, SESSION_COUNT_ROLE) == original
