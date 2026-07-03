import json
import shutil

import pytest

from tests.fixtures import build_claude_fixture, _write_session
from cc_history_tidy.migrator import MigrationConflictError, migrate_sessions
from cc_history_tidy.models import MigrationMode


def test_copy_migration_keeps_source_metadata(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.COPY,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )

    assert result.copied
    assert not result.removed
    assert source_file.exists()
    assert (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    ).exists()


def test_move_migration_removes_source_after_copy(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.MOVE,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )

    assert result.copied
    assert result.removed
    assert not source_file.exists()
    assert (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    ).exists()


def test_move_migration_can_move_within_same_account_to_another_group(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    target_group_id = "33333333-3333-4333-8333-333333333333"
    source_file = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-current.json"
    )

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.current_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.MOVE,
        backup_root=tmp_path / "backups",
        target_group_id=target_group_id,
    )

    assert result.copied
    assert result.removed
    assert not source_file.exists()
    assert (
        fixture.sessions_root
        / fixture.current_account_uuid
        / target_group_id
        / "session-current.json"
    ).exists()


def test_migration_rejects_existing_target_file(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )
    target_file = (
        fixture.sessions_root
        / fixture.current_account_uuid
        / fixture.current_group_id
        / "session-source.json"
    )
    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target_file)

    with pytest.raises(MigrationConflictError):
        migrate_sessions(
            sessions_root=fixture.sessions_root,
            source_account_uuid=fixture.source_account_uuid,
            target_account_uuid=fixture.current_account_uuid,
            session_files=[source_file],
            mode=MigrationMode.COPY,
            backup_root=tmp_path / "backups",
            target_group_id=fixture.current_group_id,
        )


def test_migration_rejects_empty_target_group_id(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )

    with pytest.raises(ValueError, match="target_group_id"):
        migrate_sessions(
            sessions_root=fixture.sessions_root,
            source_account_uuid=fixture.source_account_uuid,
            target_account_uuid=fixture.current_account_uuid,
            session_files=[source_file],
            mode=MigrationMode.MOVE,
            backup_root=tmp_path / "backups",
            target_group_id="",
        )
    assert source_file.exists()


def test_copy_migration_rewrites_session_id(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_dir = fixture.sessions_root / fixture.source_account_uuid / fixture.source_group_id
    # Real Claude Desktop files are named <sessionId>.json.
    real_style = source_dir / "local_11111111-aaaa-4aaa-8aaa-111111111111.json"
    _write_session(
        real_style,
        "local_11111111-aaaa-4aaa-8aaa-111111111111",
        "cli-realstyle",
        "Real style session",
    )

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[real_style],
        mode=MigrationMode.COPY,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )

    (target,) = result.copied
    source_data = json.loads(real_style.read_text(encoding="utf-8"))
    target_data = json.loads(target.read_text(encoding="utf-8"))
    # The copy must not share a sessionId with the original: per-root group
    # assignments are keyed by code:<sessionId>.
    assert target_data["sessionId"] != source_data["sessionId"]
    assert target_data["sessionId"].startswith("local_")
    assert target_data["cliSessionId"] == source_data["cliSessionId"]
    # Filename keeps the <sessionId>.json convention.
    assert target.stem == target_data["sessionId"]


def test_move_migration_keeps_session_id(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )

    result = migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.MOVE,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )

    (target,) = result.copied
    assert json.loads(target.read_text(encoding="utf-8"))["sessionId"] == "desktop-source"


def test_migration_rejects_duplicate_targets_within_batch(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    account_dir = fixture.sessions_root / fixture.source_account_uuid
    other_group = account_dir / "33333333-3333-4333-8333-333333333333"
    other_group.mkdir()
    duplicate_name = account_dir / fixture.source_group_id / "session-source.json"
    second_source = other_group / "session-source.json"
    shutil.copy2(duplicate_name, second_source)

    with pytest.raises(MigrationConflictError, match="same target"):
        migrate_sessions(
            sessions_root=fixture.sessions_root,
            source_account_uuid=fixture.source_account_uuid,
            target_account_uuid=fixture.current_account_uuid,
            session_files=[duplicate_name, second_source],
            mode=MigrationMode.MOVE,
            backup_root=tmp_path / "backups",
            target_group_id=fixture.current_group_id,
        )
    assert duplicate_name.exists()
    assert second_source.exists()


def test_move_migration_prunes_empty_source_dirs(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    source_group_dir = fixture.sessions_root / fixture.source_account_uuid / fixture.source_group_id
    source_file = source_group_dir / "session-source.json"

    migrate_sessions(
        sessions_root=fixture.sessions_root,
        source_account_uuid=fixture.source_account_uuid,
        target_account_uuid=fixture.current_account_uuid,
        session_files=[source_file],
        mode=MigrationMode.MOVE,
        backup_root=tmp_path / "backups",
        target_group_id=fixture.current_group_id,
    )

    # The emptied group dir (and the now-empty account dir) must not linger as
    # phantom entries for Claude Desktop.
    assert not source_group_dir.exists()
    assert not (fixture.sessions_root / fixture.source_account_uuid).exists()
    assert fixture.sessions_root.exists()
