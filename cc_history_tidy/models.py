from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path


class MigrationMode(str, Enum):
    COPY = "copy"
    MOVE = "move"


@dataclass(frozen=True)
class AccountPartition:
    account_uuid: str
    root: Path
    is_current: bool

    @property
    def display_name(self) -> str:
        digest = hashlib.sha256(self.account_uuid.encode("utf-8")).hexdigest()[:8].upper()
        suffix = "current" if self.is_current else "source"
        return f"Account {digest} ({suffix})"


@dataclass(frozen=True)
class ClaudeSession:
    metadata_path: Path
    sessions_root: Path
    account_uuid: str
    session_id: str
    cli_session_id: str
    group_id: str
    title: str
    cwd: str
    created_at: int | None
    last_activity_at: int | None
    archived: bool
    transcript_path: Path | None
    group_label: str = ""
    code_group_id: str = "ungrouped"
    code_group_label: str = "Ungrouped"
    code_group_order: int = 1_000_000
    code_session_order: int = 1_000_000

    @property
    def has_transcript(self) -> bool:
        return self.transcript_path is not None and self.transcript_path.exists()


@dataclass(frozen=True)
class ScannedAccount:
    partition: AccountPartition
    sessions: tuple[ClaudeSession, ...]
    # Groups defined in the root's layout that currently contain no sessions
    # anywhere in that root: (code_group_id, label) pairs. Group definitions
    # are per install root, so the same empty groups are attached to every
    # account of the root.
    empty_code_groups: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MigrationItem:
    source: ClaudeSession
    target_metadata_path: Path


@dataclass(frozen=True)
class MigrationPlan:
    mode: MigrationMode
    target_account: AccountPartition
    items: tuple[MigrationItem, ...]


@dataclass(frozen=True)
class MigrationResult:
    copied: tuple[Path, ...]
    removed: tuple[Path, ...]
    backup_root: Path
    # (old sessionId, new sessionId) for COPY migrations; empty for MOVE.
    session_id_mapping: tuple[tuple[str, str], ...] = ()
