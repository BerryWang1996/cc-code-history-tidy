"""Minimal LevelDB write-ahead-log appender for Chromium localStorage.

Chromium persists the renderer's ``window.localStorage`` in a LevelDB
directory. This module appends PUT records to the database's active ``.log``
file using the standard LevelDB log/WriteBatch formats, so that the next
process to open the database (Claude Desktop's own LevelDB) replays them and
sees the new values. Records are written with a sequence number above
everything already in the database, which makes them authoritative.

Safe ONLY while no other process has the database open — callers must ensure
Claude Desktop is closed (the app already enforces this before Execute).

Formats implemented (see leveldb's ``db/log_format.h`` and
``db/write_batch.cc``):

- log file: 32768-byte blocks; each physical record is
  ``crc32c(4, masked) + length(2, LE) + type(1)`` followed by payload, where
  type is FULL/FIRST/MIDDLE/LAST. Blocks with fewer than 7 trailing bytes are
  zero-padded.
- WriteBatch payload: ``sequence(8, LE) + count(4, LE)`` then per operation
  ``0x01 + varint32(len(key)) + key + varint32(len(value)) + value`` for PUT.

Chromium localStorage encoding (see ``components/services/storage``):

- record key: ``b"_" + storage_key + b"\\x00" + prefixed(script_key)``
- values and script keys carry a 1-byte type prefix: ``0x00`` UTF-16-LE or
  ``0x01`` Latin-1.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

LOG_BLOCK_SIZE = 32768
_HEADER_SIZE = 7
_FULL, _FIRST, _MIDDLE, _LAST = 1, 2, 3, 4

_LOG_NAME_RE = re.compile(r"^(?P<num>\d{6,})\.log$")

# --- crc32c (Castagnoli), reflected, table-driven ---------------------------

_CRC32C_POLY = 0x82F63B78


def _build_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ _CRC32C_POLY if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_TABLE = _build_table()


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def masked_crc32c(data: bytes) -> int:
    """LevelDB stores CRCs 'masked' to tolerate CRC-of-CRC data."""
    crc = crc32c(data)
    return (((crc >> 15) | (crc << 17)) + 0xA282EAD8) & 0xFFFFFFFF


# --- encoding helpers --------------------------------------------------------


def _varint32(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def encode_string(text: str) -> bytes:
    """Chromium type-prefixed string: Latin-1 when possible, else UTF-16-LE."""
    try:
        return b"\x01" + text.encode("iso-8859-1")
    except UnicodeEncodeError:
        return b"\x00" + text.encode("utf-16-le")


def make_localstorage_key(storage_key: str, script_key: str) -> bytes:
    return b"_" + storage_key.encode("iso-8859-1") + b"\x00" + encode_string(script_key)


def build_write_batch(sequence: int, puts: dict[bytes, bytes]) -> bytes:
    body = bytearray(struct.pack("<QI", sequence, len(puts)))
    for key, value in puts.items():
        body.append(0x01)  # kTypeValue (PUT)
        body += _varint32(len(key))
        body += key
        body += _varint32(len(value))
        body += value
    return bytes(body)


# --- log framing --------------------------------------------------------------


def _frame_record(payload: bytes, block_offset: int) -> tuple[bytes, int]:
    """Split ``payload`` into physical log records starting at ``block_offset``
    within a 32KB block. Returns (bytes to append, new block offset)."""
    out = bytearray()
    pos = block_offset
    remaining = payload
    first = True
    while True:
        leftover = LOG_BLOCK_SIZE - pos
        if leftover < _HEADER_SIZE:
            out += b"\x00" * leftover
            pos = 0
            leftover = LOG_BLOCK_SIZE
        avail = leftover - _HEADER_SIZE
        fragment = remaining[:avail]
        remaining = remaining[len(fragment):]
        last = not remaining
        if first and last:
            rec_type = _FULL
        elif first:
            rec_type = _FIRST
        elif last:
            rec_type = _LAST
        else:
            rec_type = _MIDDLE
        crc = masked_crc32c(bytes([rec_type]) + fragment)
        out += struct.pack("<IHB", crc, len(fragment), rec_type)
        out += fragment
        pos = (pos + _HEADER_SIZE + len(fragment)) % LOG_BLOCK_SIZE
        if last:
            return bytes(out), pos
        first = False


def _active_log_path(leveldb_dir: Path) -> Path:
    logs = []
    max_file_number = 0
    for entry in leveldb_dir.iterdir():
        match = _LOG_NAME_RE.match(entry.name)
        if match:
            logs.append((int(match.group("num")), entry))
        stem = entry.name.split(".")[0].split("-")[-1]
        if stem.isdigit():
            max_file_number = max(max_file_number, int(stem))
    if logs:
        return max(logs)[1]
    return leveldb_dir / f"{max_file_number + 1:06d}.log"


def append_puts(leveldb_dir: Path, sequence: int, puts: dict[bytes, bytes]) -> Path:
    """Append a WriteBatch of PUTs to the database's active log file.

    Args:
        leveldb_dir: the ``Local Storage/leveldb`` directory.
        sequence: base sequence for the batch — must exceed every sequence
            already present in the database.
        puts: mapping of raw leveldb key -> raw value.

    Returns:
        The log file that was written.
    """
    if not puts:
        raise ValueError("No records to write")
    lock = leveldb_dir / "LOCK"
    if not leveldb_dir.is_dir():
        raise NotADirectoryError(leveldb_dir)
    log_path = _active_log_path(leveldb_dir)
    payload = build_write_batch(sequence, puts)
    existing = log_path.stat().st_size if log_path.exists() else 0
    framed, _ = _frame_record(payload, existing % LOG_BLOCK_SIZE)
    with log_path.open("ab") as handle:
        handle.write(framed)
        handle.flush()
    # keep an (empty) LOCK file around like leveldb does for fresh dirs
    if not lock.exists():
        lock.touch()
    return log_path
