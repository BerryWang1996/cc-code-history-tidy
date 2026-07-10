import json

from chromium_reader import LocalStorageReader

from cc_history_tidy.backup import create_backup, restore_backup
from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.leveldb_writer import append_puts, encode_string, make_localstorage_key
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture


def _seed_renderer_store(claude_root, origin="app://localhost"):
    leveldb = claude_root / "Local Storage" / "leveldb"
    leveldb.mkdir(parents=True)
    store = {
        "state": {
            "sidebarWidth": 300,
            "customGroups": [],
            "customGroupAssignments": {},
            "customGroupOrder": {},
        },
        "version": 7,
    }
    append_puts(
        leveldb,
        1,
        {
            make_localstorage_key(origin, "dframe-store"): encode_string(
                json.dumps(store, separators=(",", ":"))
            )
        },
    )
    return leveldb


def _live_store_state(leveldb, origin="app://localhost"):
    reader = LocalStorageReader(leveldb)
    try:
        best = None
        for rec in reader.records(include_deletions=False):
            if rec.storage_key != origin or rec.script_key != "dframe-store":
                continue
            if best is None or rec.leveldb_seq_number > best.leveldb_seq_number:
                best = rec
        return json.loads(best.value)["state"]
    finally:
        reader.close()


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


def test_execute_writes_group_definitions_into_local_storage(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    leveldb = _seed_renderer_store(fixture.sessions_root.parent)
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        execute_confirmer=lambda summary: True,
    )
    window.load_environment(env)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    tree.setCurrentItem(source_group)
    tree.cut_selected_sessions()
    tree.paste_to(current_account)

    window.execute_plan()

    state = _live_store_state(leveldb)
    labels = {group["id"]: group["name"] for group in state["customGroups"]}
    assert labels[fixture.source_code_group_id] == "Archive Code Group"
    assert state["customGroupAssignments"]["code:desktop-source"] == fixture.source_code_group_id
    assert state["sidebarWidth"] == 300  # unrelated renderer state preserved


def test_backup_and_restore_cover_local_storage(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    leveldb = _seed_renderer_store(fixture.sessions_root.parent)
    before = _live_store_state(leveldb)

    backup = create_backup(fixture.sessions_root, tmp_path / "backups", reason="unit")
    # mutate the store after the backup
    append_puts(
        leveldb,
        500,
        {
            make_localstorage_key("app://localhost", "dframe-store"): encode_string(
                json.dumps({"state": {"sidebarWidth": 1}}, separators=(",", ":"))
            )
        },
    )
    assert _live_store_state(leveldb)["sidebarWidth"] == 1

    restore_backup(backup)

    assert _live_store_state(leveldb) == before


def test_execute_warns_when_localstorage_write_skipped(tmp_path):
    # No renderer store exists (Desktop UI never opened): the config is written
    # but the LevelDB group definitions cannot be, and Execute must surface a
    # warning instead of silently reporting plain success.
    fixture = build_claude_fixture(tmp_path)
    # deliberately DO NOT seed a dframe-store; create an empty leveldb dir
    (fixture.sessions_root.parent / "Local Storage" / "leveldb").mkdir(parents=True)
    env = discover_claude_environment(
        fixture.user_profile, fixture.appdata, fixture.localappdata
    )
    create_app([])
    seen = {}
    window = MainWindow(
        backup_parent=tmp_path / "backups",
        process_checker=lambda: False,
        execute_confirmer=lambda summary: True,
        info_notifier=lambda title, body: seen.update(title=title, body=body),
    )
    window.load_environment(env)
    tree = window.session_tree
    source_group = _find_item_by_data(tree, fixture.source_code_group_id)
    current_account = _find_item_by_data(tree, fixture.current_account_uuid)
    tree.setCurrentItem(source_group)
    tree.cut_selected_sessions()
    tree.paste_to(current_account)

    window.execute_plan()

    # the warning notification fired and the status bar notes the skip
    assert seen, "expected a skipped-localstorage warning"
    from cc_history_tidy import i18n
    assert i18n.tr("status.localstorage_skipped_suffix") in window.status_label.text()

