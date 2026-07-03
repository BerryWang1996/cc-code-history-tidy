from tests.fixtures import build_claude_fixture
from cc_history_tidy.backup import create_backup, list_backups, restore_backup


def test_backup_and_restore_sessions_root(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"

    backup = create_backup(fixture.sessions_root, backup_root, reason="unit-test")
    source_file = (
        fixture.sessions_root
        / fixture.source_account_uuid
        / fixture.source_group_id
        / "session-source.json"
    )
    source_file.unlink()

    restore_backup(backup)

    assert source_file.exists()
    assert (backup.root / "backup-manifest.json").exists()


def test_backup_and_restore_desktop_config(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"
    config_path = fixture.sessions_root.parent / "claude_desktop_config.json"

    backup = create_backup(
        fixture.sessions_root,
        backup_root,
        reason="unit-test",
        config_path=config_path,
    )
    config_path.write_text('{"changed": true}', encoding="utf-8")

    restore_backup(backup)

    assert "epitaxyPrefs" in config_path.read_text(encoding="utf-8")
    assert (backup.root / "claude_desktop_config.json").exists()


def test_list_backups_loads_manifest_snapshots(tmp_path):
    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"
    created = create_backup(fixture.sessions_root, backup_root, reason="unit-test")

    backups = list_backups(backup_root)

    assert [backup.root for backup in backups] == [created.root]
    assert backups[0].sessions_root == fixture.sessions_root
