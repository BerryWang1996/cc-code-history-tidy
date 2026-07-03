from pathlib import Path

from cc_history_tidy.models import AccountPartition, ClaudeSession, MigrationMode


def test_account_hash_does_not_expose_uuid():
    account = AccountPartition(
        account_uuid="11111111-2222-3333-4444-555555555555",
        root=Path("accounts/source"),
        is_current=False,
    )

    assert account.display_name.startswith("Account ")
    assert "11111111" not in account.display_name


def test_session_can_report_missing_transcript():
    session = ClaudeSession(
        metadata_path=Path("session.json"),
        account_uuid="source",
        session_id="desktop-session",
        cli_session_id="cli-session",
        group_id="group",
        title="A title",
        cwd="C:/work/project",
        created_at=1,
        last_activity_at=2,
        archived=False,
        transcript_path=None,
        group_label="Group",
    )

    assert not session.has_transcript
    assert MigrationMode.COPY.value == "copy"
