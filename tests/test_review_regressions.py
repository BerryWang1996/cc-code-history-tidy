"""Regression tests for issues found during adversarial review of the fixes."""

import json

import pytest

from cc_history_tidy.backup import create_backup, restore_backup
from cc_history_tidy.gui import MainWindow, create_app
from cc_history_tidy.migrator import MigrationConflictError, migrate_sessions
from cc_history_tidy.models import MigrationMode
from cc_history_tidy.paths import discover_claude_environment
from tests.fixtures import build_claude_fixture, _write_session


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


def test_copy_execute_keeps_original_grouping_and_writes_no_stale_target_entry(tmp_path):
    """COPY must not degroup the original or write the old id into the target config."""
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

    config = json.loads(
        (fixture.sessions_root.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    slice_data = config["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    # The original stays in the source account and must keep its group.
    assert slice_data["customGroupAssignments"]["code:desktop-source"] == fixture.source_code_group_id
    # The dragged tree item must not smuggle the OLD id into the target group.
    assert "code:desktop-source" not in slice_data["customGroupOrder"].get(
        fixture.current_code_group_id, []
    )
    # The copy exists with a fresh id and is intentionally ungrouped.
    copies = list(
        (fixture.sessions_root / fixture.current_account_uuid / fixture.current_group_id).glob("*.json")
    )
    copied_ids = {
        json.loads(path.read_text(encoding="utf-8"))["sessionId"] for path in copies
    }
    assert "desktop-source" not in copied_ids
    fresh_ids = copied_ids - {"desktop-current", "desktop-ungrouped"}
    assert len(fresh_ids) == 1  # exactly one fresh-id copy arrived


def test_restore_removes_config_created_after_backup(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    config_path = fixture.sessions_root.parent / "created-later-config.json"
    assert not config_path.exists()
    backup = create_backup(
        fixture.sessions_root,
        tmp_path / "backups",
        reason="unit",
        config_path=config_path,
    )
    # Simulate a failed run creating the config after the backup was taken.
    config_path.write_text("{}", encoding="utf-8")

    restore_backup(backup)

    assert not config_path.exists()


def test_move_rejects_duplicate_session_id_in_target_root(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )
    # The same session id already lives in the target root under another name.
    preexisting = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "other-name.json"
    )
    _write_session(preexisting, "desktop-source", "cli-source", "Pre-existing duplicate")

    with pytest.raises(MigrationConflictError, match="desktop-source"):
        migrate_sessions(
            sessions_root=fixture.sessions_root,
            source_account_uuid=fixture.source_account_uuid,
            target_account_uuid=fixture.current_account_uuid,
            session_files=[source_file],
            mode=MigrationMode.MOVE,
            backup_root=tmp_path / "backups",
            target_group_id=fixture.current_group_id,
        )
    assert source_file.exists()
