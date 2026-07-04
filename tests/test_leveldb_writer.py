from chromium_reader import LocalStorageReader

from cc_history_tidy.leveldb_writer import (
    LOG_BLOCK_SIZE,
    append_puts,
    crc32c,
    encode_string,
    make_localstorage_key,
)


def _live_value(leveldb_dir, storage_key, script_key):
    reader = LocalStorageReader(leveldb_dir)
    try:
        best = None
        for rec in reader.records(include_deletions=True):
            if rec.storage_key != storage_key or rec.script_key != script_key:
                continue
            if best is None or rec.leveldb_seq_number > best.leveldb_seq_number:
                best = rec
        return None if best is None else best.value
    finally:
        reader.close()


def test_crc32c_known_vectors():
    # RFC 3720 test vector: 32 bytes of zeros
    assert crc32c(b"\x00" * 32) == 0x8A9136AA
    assert crc32c(b"123456789") == 0xE3069283


def test_written_records_round_trip_via_independent_reader(tmp_path):
    ldb = tmp_path / "leveldb"
    ldb.mkdir()
    key = make_localstorage_key("app://localhost", "dframe-store")
    append_puts(ldb, 1, {key: encode_string('{"state":{"a":1}}')})

    assert _live_value(ldb, "app://localhost", "dframe-store") == '{"state":{"a":1}}'


def test_higher_sequence_wins_on_append(tmp_path):
    ldb = tmp_path / "leveldb"
    ldb.mkdir()
    key = make_localstorage_key("https://claude.ai", "dframe-store")
    append_puts(ldb, 1, {key: encode_string("old")})
    append_puts(ldb, 50, {key: encode_string("new")})

    assert _live_value(ldb, "https://claude.ai", "dframe-store") == "new"


def test_multiple_puts_in_one_batch(tmp_path):
    ldb = tmp_path / "leveldb"
    ldb.mkdir()
    puts = {
        make_localstorage_key("app://localhost", "dframe-store"): encode_string("v1"),
        make_localstorage_key("app://localhost", "LSS-persisted.dframe-local-slice"): encode_string("v2"),
    }
    append_puts(ldb, 10, puts)

    assert _live_value(ldb, "app://localhost", "dframe-store") == "v1"
    assert _live_value(ldb, "app://localhost", "LSS-persisted.dframe-local-slice") == "v2"


def test_record_spanning_block_boundary(tmp_path):
    ldb = tmp_path / "leveldb"
    ldb.mkdir()
    key = make_localstorage_key("app://localhost", "big")
    big_value = "x" * (LOG_BLOCK_SIZE + 5000)
    append_puts(ldb, 1, {key: encode_string(big_value)})
    # and a second write near the block boundary
    key2 = make_localstorage_key("app://localhost", "after")
    append_puts(ldb, 2, {key2: encode_string("tail")})

    assert _live_value(ldb, "app://localhost", "big") == big_value
    assert _live_value(ldb, "app://localhost", "after") == "tail"


def test_non_latin_values_use_utf16(tmp_path):
    ldb = tmp_path / "leveldb"
    ldb.mkdir()
    key = make_localstorage_key("app://localhost", "dframe-store")
    append_puts(ldb, 1, {key: encode_string('{"名字":"ixoran开发计划推进"}')})

    assert _live_value(ldb, "app://localhost", "dframe-store") == '{"名字":"ixoran开发计划推进"}'
