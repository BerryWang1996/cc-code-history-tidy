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
