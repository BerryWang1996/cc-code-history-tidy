import json

from cc_history_tidy import code_groups
from cc_history_tidy.code_groups import _slice_from_local_storage_record, load_code_group_layout
from cc_history_tidy.paths import ClaudeEnvironment


def test_dframe_store_record_exposes_custom_group_names():
    raw_value = json.dumps(
        {
            "state": {
                "customGroups": [
                    {"id": "cg-ledger", "name": "记账测试"},
                ],
                "customGroupAssignments": {
                    "code:local-a": "cg-ledger",
                },
                "customGroupOrder": {
                    "cg-ledger": ["code:local-a"],
                },
            },
            "version": 0,
        },
        ensure_ascii=False,
    )

    slice_data = _slice_from_local_storage_record("dframe-store", raw_value)

    assert slice_data["customGroups"][0]["name"] == "记账测试"


def test_load_code_group_layout_merges_names_with_config_assignments(monkeypatch, tmp_path):
    env = ClaudeEnvironment(
        user_profile=tmp_path,
        appdata=tmp_path,
        localappdata=tmp_path,
        claude_config=tmp_path / ".claude.json",
        transcript_root=tmp_path / ".claude" / "projects",
        sessions_root=tmp_path / "Claude" / "claude-code-sessions",
        sessions_roots=(tmp_path / "Claude" / "claude-code-sessions",),
        current_account_uuid="account-a",
    )
    desktop_slice = {
        "customGroupAssignments": {"code:local-a": "cg-ledger"},
        "customGroupOrder": {"cg-ledger": ["code:local-a"]},
    }
    local_storage_slice = {
        "customGroups": [{"id": "cg-ledger", "name": "记账测试"}],
    }
    monkeypatch.setattr(code_groups, "_read_desktop_slice", lambda _path: desktop_slice)
    monkeypatch.setattr(code_groups, "_read_local_storage_slice", lambda _path: local_storage_slice)

    layout = load_code_group_layout(env)

    assert layout.group_for_session("local-a") == "cg-ledger"
    assert layout.label_for_group("cg-ledger") == "记账测试"
    assert layout.order_for_group("cg-ledger") == 0
    assert layout.order_for_session("local-a") == 0


def test_load_code_group_layout_prefers_desktop_assignments_over_stale_local_storage(monkeypatch, tmp_path):
    env = ClaudeEnvironment(
        user_profile=tmp_path,
        appdata=tmp_path,
        localappdata=tmp_path,
        claude_config=tmp_path / ".claude.json",
        transcript_root=tmp_path / ".claude" / "projects",
        sessions_root=tmp_path / "Claude" / "claude-code-sessions",
        sessions_roots=(tmp_path / "Claude" / "claude-code-sessions",),
        current_account_uuid="account-a",
    )
    desktop_slice = {
        "customGroupAssignments": {"code:local-a": "cg-new"},
        "customGroupOrder": {"cg-new": ["code:local-a"]},
    }
    stale_local_storage_slice = {
        "customGroups": [
            {"id": "cg-old", "name": "Old group"},
            {"id": "cg-new", "name": "New group"},
        ],
        "customGroupAssignments": {"code:local-a": "cg-old"},
        "customGroupOrder": {"cg-old": ["code:local-a"]},
    }
    monkeypatch.setattr(code_groups, "_read_desktop_slice", lambda _path: desktop_slice)
    monkeypatch.setattr(code_groups, "_read_local_storage_slice", lambda _path: stale_local_storage_slice)

    layout = load_code_group_layout(env)

    assert layout.group_for_session("local-a") == "cg-new"
    assert layout.label_for_group("cg-new") == "New group"
    assert layout.order_for_group("cg-new") == 0
