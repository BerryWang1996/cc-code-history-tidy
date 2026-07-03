import shutil

import pytest

from tests.fixtures import build_claude_fixture
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
