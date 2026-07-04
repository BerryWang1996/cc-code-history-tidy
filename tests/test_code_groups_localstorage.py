import json

from chromium_reader import LocalStorageReader

from cc_history_tidy.code_groups import (
    _read_local_storage_slice,
    save_code_group_layout_to_local_storage,
)
from cc_history_tidy.leveldb_writer import append_puts, encode_string, make_localstorage_key


def _seed_gateway_store(claude_root, origin="app://localhost"):
    leveldb = claude_root / "Local Storage" / "leveldb"
    leveldb.mkdir(parents=True)
    store = {
        "state": {
            "sidebarWidth": 280,
            "collapsed": False,
            "customGroups": [],
            "customGroupAssignments": {"code:stale": "cg-old"},
            "customGroupOrder": {"cg-old": ["code:stale"]},
            "pinnedOrder": ["code:pinned"],
        },
        "version": 7,
    }
    lss = {
        "value": {
            "customGroupAssignments": {"code:stale": "cg-old"},
            "customGroupOrder": {"cg-old": ["code:stale"]},
            "pinnedOrder": [],
        },
        "tabId": "abc",
    }
    append_puts(
        leveldb,
        1,
        {
            make_localstorage_key(origin, "dframe-store"): encode_string(
                json.dumps(store, separators=(",", ":"))
            ),
            make_localstorage_key(origin, "LSS-persisted.dframe-local-slice"): encode_string(
                json.dumps(lss, separators=(",", ":"))
            ),
        },
    )
    return leveldb


def _live_json(leveldb, origin, script_key):
    reader = LocalStorageReader(leveldb)
    try:
        best = None
        for rec in reader.records(include_deletions=False):
            if rec.storage_key != origin or rec.script_key != script_key:
                continue
            if best is None or rec.leveldb_seq_number > best.leveldb_seq_number:
                best = rec
        return json.loads(best.value)
    finally:
        reader.close()


def test_save_layout_writes_groups_into_dframe_store(tmp_path):
    claude_root = tmp_path / "Claude-3p"
    leveldb = _seed_gateway_store(claude_root)

    wrote = save_code_group_layout_to_local_storage(
        claude_root,
        visible_session_keys={"code:s1", "code:stale"},
        assignments={"code:s1": "cg-ixoran"},
        order_data={"cg-ixoran": ["code:s1"]},
        group_labels={"cg-ixoran": "ixoran开发计划推进"},
    )

    assert wrote is True
    store = _live_json(leveldb, "app://localhost", "dframe-store")
    state = store["state"]
    # our layout landed
    assert state["customGroupAssignments"] == {"code:s1": "cg-ixoran"}
    assert state["customGroupOrder"]["cg-ixoran"] == ["code:s1"]
    assert {g["id"]: g["name"] for g in state["customGroups"]} == {"cg-ixoran": "ixoran开发计划推进"}
    # unrelated renderer state preserved
    assert state["sidebarWidth"] == 280
    assert state["pinnedOrder"] == ["code:pinned"]
    assert store["version"] == 7

    lss = _live_json(leveldb, "app://localhost", "LSS-persisted.dframe-local-slice")
    assert lss["value"]["customGroupAssignments"] == {"code:s1": "cg-ixoran"}
    assert lss["tabId"] == "abc"
    # the local slice never carries group names
    assert "customGroups" not in lss["value"]


def test_save_layout_purges_visible_keys_but_keeps_foreign_assignments(tmp_path):
    claude_root = tmp_path / "Claude"
    leveldb = _seed_gateway_store(claude_root, origin="https://claude.ai")

    save_code_group_layout_to_local_storage(
        claude_root,
        visible_session_keys={"code:s1"},  # 'code:stale' NOT visible -> kept
        assignments={"code:s1": "cg-a"},
        order_data={"cg-a": ["code:s1"]},
        group_labels={"cg-a": "A"},
    )

    state = _live_json(leveldb, "https://claude.ai", "dframe-store")["state"]
    assert state["customGroupAssignments"] == {"code:stale": "cg-old", "code:s1": "cg-a"}


def test_save_layout_skips_when_no_leveldb(tmp_path):
    assert (
        save_code_group_layout_to_local_storage(
            tmp_path / "nonexistent",
            visible_session_keys=set(),
            assignments={},
            order_data={},
        )
        is False
    )


def test_save_layout_skips_when_renderer_never_ran(tmp_path):
    claude_root = tmp_path / "Claude"
    (claude_root / "Local Storage" / "leveldb").mkdir(parents=True)
    assert (
        save_code_group_layout_to_local_storage(
            claude_root,
            visible_session_keys=set(),
            assignments={},
            order_data={},
        )
        is False
    )


def test_read_slice_accepts_gateway_origin(tmp_path):
    claude_root = tmp_path / "Claude-3p"
    leveldb = _seed_gateway_store(claude_root)

    slice_data = _read_local_storage_slice(leveldb)

    assert slice_data.get("customGroupAssignments") == {"code:stale": "cg-old"}
