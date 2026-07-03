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


def test_cut_dims_items_and_clear_restores(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = group.child(0)
    tree.setCurrentItem(session_item)

    assert tree.cut_selected_sessions() == 1
    assert tree.clipboard_mode == MigrationMode.MOVE
    assert tree.clipboard_items == [session_item]
    assert session_item.foreground(0).color().name() == "#969696"

    tree.clear_clipboard()
    assert tree.clipboard_mode is None
    assert tree.clipboard_items == []


def test_copy_sets_clipboard_without_dimming(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = group.child(0)
    tree.setCurrentItem(session_item)

    assert tree.copy_selected_sessions() == 1
    assert tree.clipboard_mode == MigrationMode.COPY
    assert session_item.foreground(0).color().name() != "#969696"


def test_new_copy_overwrites_old_cut(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_group = _find_item_by_data(tree, fixture.current_code_group_id)
    cut_item = source_group.child(0)
    tree.setCurrentItem(cut_item)
    tree.cut_selected_sessions()

    tree.setCurrentItem(current_group.child(0))
    tree.copy_selected_sessions()

    assert tree.clipboard_mode == MigrationMode.COPY
    assert cut_item not in tree.clipboard_items
    # old cut item is restored to the normal foreground
    assert cut_item.foreground(0).color().name() != "#969696"


def test_clipboard_ignores_group_and_account_selection(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    group = _find_item_by_data(tree, fixture.source_code_group_id)
    tree.setCurrentItem(group)

    assert tree.cut_selected_sessions() == 0
    assert tree.clipboard_mode is None


def test_paste_cut_into_group_moves_item(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    assert tree.paste_to(target_group) == 1
    assert session_item.parent() is target_group
    assert tree.clipboard_mode is None  # cut clipboard clears after paste
    # cross-account move gets the badge
    assert session_item.text(1) == "待移入"


def test_paste_copy_creates_ghost_and_allows_repeat(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.copy_selected_sessions()

    assert tree.paste_to(target_group) == 1
    assert tree.paste_to(target_group) == 1  # copy clipboard survives
    ghosts = [
        target_group.child(i)
        for i in range(target_group.childCount())
        if tree.is_ghost_item(target_group.child(i))
    ]
    assert len(ghosts) == 2
    assert all(g.text(1) == "⊕ 待复制" for g in ghosts)
    # source stays put
    assert session_item.parent() is source_group


def test_paste_to_account_lands_in_ungrouped(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    assert tree.paste_to(current_account) == 1
    assert session_item.parent().data(0, 256) == "ungrouped"


def test_paste_to_session_inserts_after_it(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)
    anchor = target_group.child(0)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    tree.paste_to(anchor)

    assert target_group.indexOfChild(session_item) == target_group.indexOfChild(anchor) + 1


def test_paste_with_empty_clipboard_is_noop(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    target_group = _find_item_by_data(tree, fixture.current_code_group_id)

    assert tree.paste_to(target_group) == 0


def test_cut_paste_back_to_origin_is_noop(tmp_path):
    fixture, window = _load_window(tmp_path)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    session_item = source_group.child(0)
    tree.setCurrentItem(session_item)
    tree.cut_selected_sessions()

    tree.paste_to(source_group)

    assert session_item.parent() is source_group
    assert session_item.text(1) != "待移入"
    assert window.planned_session_moves() == []
    assert window.tree_signature() == window._loaded_tree_signature


def test_remove_ghost_item_undoes_staged_copy(tmp_path):
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

    assert all(
        not tree.is_ghost_item(target_group.child(i))
        for i in range(target_group.childCount())
    )
