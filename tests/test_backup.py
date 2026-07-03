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


def test_create_backup_names_do_not_collide_within_same_tick(tmp_path, monkeypatch):
    from datetime import datetime

    from cc_history_tidy import backup as backup_module

    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"
    frozen = datetime(2026, 7, 3, 12, 0, 0, 123456)

    class FrozenDateTime:
        @staticmethod
        def now(_tz=None):
            return frozen

    monkeypatch.setattr(backup_module, "datetime", FrozenDateTime)

    first = create_backup(fixture.sessions_root, backup_root, reason="a")
    second = create_backup(fixture.sessions_root, backup_root, reason="b")

    assert first.root != second.root
    assert first.snapshot_root.exists()
    assert second.snapshot_root.exists()


def test_restore_backup_from_moved_backup_directory(tmp_path):
    import shutil

    from cc_history_tidy.backup import load_backup

    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"
    backup = create_backup(fixture.sessions_root, backup_root, reason="portable")

    moved_parent = tmp_path / "moved-backups"
    moved_parent.mkdir()
    moved_root = moved_parent / backup.root.name
    shutil.move(str(backup.root), str(moved_root))

    source_file = fixture.sessions_root / fixture.source_account_uuid / fixture.source_group_id / "session-source.json"
    source_file.unlink()

    restore_backup(load_backup(moved_root))

    assert source_file.exists()


def test_create_backup_cleans_up_partial_snapshot_on_failure(tmp_path, monkeypatch):
    import shutil as shutil_module

    from cc_history_tidy import backup as backup_module

    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"

    def fail_copytree(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backup_module.shutil, "copytree", fail_copytree)

    try:
        create_backup(fixture.sessions_root, backup_root, reason="fails")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")

    from cc_history_tidy.backup import list_backups

    assert list_backups(backup_root) == []
    assert not any(backup_root.iterdir()) if backup_root.exists() else True


def test_restore_backup_keeps_live_tree_when_staging_copy_fails(tmp_path, monkeypatch):
    from cc_history_tidy import backup as backup_module

    fixture = build_claude_fixture(tmp_path)
    backup_root = tmp_path / "backups"
    backup = create_backup(fixture.sessions_root, backup_root, reason="unit")
    live_file = fixture.sessions_root / fixture.source_account_uuid / fixture.source_group_id / "session-source.json"

    real_copytree = backup_module.shutil.copytree

    def fail_copytree(src, dst, **kwargs):
        raise OSError("cannot stage")

    monkeypatch.setattr(backup_module.shutil, "copytree", fail_copytree)

    try:
        restore_backup(backup)
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")

    monkeypatch.setattr(backup_module.shutil, "copytree", real_copytree)
    assert live_file.exists()
