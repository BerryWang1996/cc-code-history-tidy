from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from cc_history_tidy.paths import ClaudeEnvironment


UNGROUPED_CODE_GROUP_ID = "ungrouped"
UNGROUPED_CODE_GROUP_LABEL = "Ungrouped"
DEFAULT_ORDER = 1_000_000


@dataclass(frozen=True)
class CodeGroupLayout:
    assignments: dict[str, str]
    group_order: dict[str, int]
    session_order: dict[str, int]
    labels: dict[str, str]

    def group_for_session(self, session_id: str) -> str:
        return self.assignments.get(_code_key(session_id), UNGROUPED_CODE_GROUP_ID)

    def label_for_group(self, group_id: str) -> str:
        if group_id == UNGROUPED_CODE_GROUP_ID:
            return UNGROUPED_CODE_GROUP_LABEL
        return self.labels.get(group_id) or f"Group {group_id.removeprefix('cg-')[:8]}"

    def order_for_group(self, group_id: str) -> int:
        if group_id == UNGROUPED_CODE_GROUP_ID:
            return DEFAULT_ORDER
        return self.group_order.get(group_id, DEFAULT_ORDER - 1)

    def order_for_session(self, session_id: str) -> int:
        return self.session_order.get(_code_key(session_id), DEFAULT_ORDER)


def load_code_group_layout(env: ClaudeEnvironment) -> CodeGroupLayout:
    claude_root = env.sessions_root.parent
    desktop_slice = _read_desktop_slice(claude_root / "claude_desktop_config.json")
    local_storage_slice = _read_local_storage_slice(claude_root / "Local Storage" / "leveldb")
    slice_data = _merge_slices(desktop_slice, local_storage_slice)

    assignments = _string_dict(slice_data.get("customGroupAssignments"))
    order_data = _list_dict(slice_data.get("customGroupOrder"))
    labels = _custom_group_labels(slice_data.get("customGroups"))
    group_order = {group_id: index for index, group_id in enumerate(order_data)}
    session_order: dict[str, int] = {}
    for group_id, session_keys in order_data.items():
        for index, session_key in enumerate(session_keys):
            session_order[session_key] = index
            assignments.setdefault(session_key, group_id)

    return CodeGroupLayout(
        assignments=assignments,
        group_order=group_order,
        session_order=session_order,
        labels=labels,
    )


def save_code_group_layout_to_desktop_config(
    config_path: Path,
    visible_session_keys: set[str],
    assignments: dict[str, str],
    order_data: dict[str, list[str]],
    group_labels: dict[str, str] | None = None,
) -> None:
    data = _read_desktop_config_strict(config_path)
    preferences = _ensure_dict(data, "preferences")
    epitaxy_prefs = _ensure_dict(preferences, "epitaxyPrefs")
    slice_data = _ensure_dict(epitaxy_prefs, "dframe-local-slice")

    existing_assignments = _string_dict(slice_data.get("customGroupAssignments"))
    for session_key in visible_session_keys:
        existing_assignments.pop(session_key, None)
    existing_assignments.update(assignments)
    slice_data["customGroupAssignments"] = existing_assignments

    existing_order = _list_dict(slice_data.get("customGroupOrder"))
    cleaned_order: dict[str, list[str]] = {}
    for group_id, session_keys in existing_order.items():
        cleaned_order[group_id] = [
            session_key for session_key in session_keys if session_key not in visible_session_keys
        ]
    for group_id, session_keys in order_data.items():
        cleaned_order[group_id] = list(session_keys)
    slice_data["customGroupOrder"] = cleaned_order

    if group_labels:
        existing_labels = _custom_group_labels(slice_data.get("customGroups"))
        existing_labels.update(group_labels)
        slice_data["customGroups"] = [
            {"id": group_id, "name": name} for group_id, name in existing_labels.items()
        ]

    _atomic_write_json(config_path, data)


DFRAME_STORE_KEY = "dframe-store"
LSS_SLICE_KEY = "LSS-persisted.dframe-local-slice"


def save_code_group_layout_to_local_storage(
    claude_root: Path,
    visible_session_keys: set[str],
    assignments: dict[str, str],
    order_data: dict[str, list[str]],
    group_labels: dict[str, str] | None = None,
) -> bool:
    """Write the staged layout into the renderer's localStorage (LevelDB).

    Claude Desktop's sidebar reads custom-group state from the renderer's
    zustand store persisted in ``Local Storage/leveldb`` (`dframe-store`).
    Group *definitions* (id+name) exist ONLY there — the desktop config only
    syncs assignments/order — so without this write a group migrated to
    another install root renders as ungrouped.

    Merges our keys into the latest live `dframe-store` and
    `LSS-persisted.dframe-local-slice` records (preserving every other field),
    appends them with an authoritative sequence number, and verifies the
    result through an independent re-read. Only safe while Claude Desktop is
    closed. Returns False when there is nothing to write to (no leveldb dir or
    no existing dframe records — e.g. the renderer never ran).
    """
    leveldb_root = claude_root / "Local Storage" / "leveldb"
    if not leveldb_root.is_dir():
        return False
    try:
        from chromium_reader import LocalStorageReader
    except ImportError:
        return False

    from cc_history_tidy.leveldb_writer import (
        append_puts,
        encode_string,
        make_localstorage_key,
    )

    latest: dict[str, object] = {}
    max_seq = 0
    reader = LocalStorageReader(leveldb_root)
    try:
        for record in reader.records(include_deletions=True):
            max_seq = max(max_seq, record.leveldb_seq_number)
            if not record.is_live or record.value is None:
                continue
            script_key = str(record.script_key)
            if script_key not in (DFRAME_STORE_KEY, LSS_SLICE_KEY):
                continue
            previous = latest.get(script_key)
            if previous is None or record.leveldb_seq_number > previous.leveldb_seq_number:
                latest[script_key] = record
    finally:
        reader.close()

    store_record = latest.get(DFRAME_STORE_KEY)
    if store_record is None:
        return False

    puts: dict[bytes, bytes] = {}
    expected: list[tuple[str, str, str]] = []

    store_data = _merge_layout_into_record_json(
        store_record.value,
        "state",
        visible_session_keys,
        assignments,
        order_data,
        group_labels,
    )
    if store_data is None:
        return False
    puts[make_localstorage_key(store_record.storage_key, DFRAME_STORE_KEY)] = encode_string(store_data)
    expected.append((store_record.storage_key, DFRAME_STORE_KEY, store_data))

    slice_record = latest.get(LSS_SLICE_KEY)
    if slice_record is not None:
        slice_data = _merge_layout_into_record_json(
            slice_record.value,
            "value",
            visible_session_keys,
            assignments,
            order_data,
            group_labels=None,  # the local slice never carries group names
        )
        if slice_data is not None:
            puts[make_localstorage_key(slice_record.storage_key, LSS_SLICE_KEY)] = encode_string(slice_data)
            expected.append((slice_record.storage_key, LSS_SLICE_KEY, slice_data))

    append_puts(leveldb_root, max_seq + 100, puts)

    # Independent verification: the values we just wrote must be the live ones.
    verify = LocalStorageReader(leveldb_root)
    try:
        live: dict[tuple[str, str], tuple[int, str | None]] = {}
        for record in verify.records(include_deletions=True):
            key = (str(record.storage_key), str(record.script_key))
            current = live.get(key)
            if current is None or record.leveldb_seq_number > current[0]:
                live[key] = (record.leveldb_seq_number, record.value)
    finally:
        verify.close()
    for storage_key, script_key, payload in expected:
        got = live.get((storage_key, script_key), (0, None))[1]
        if got != payload:
            raise RuntimeError(
                f"Local Storage write verification failed for {script_key} in {leveldb_root}"
            )
    return True


def _merge_layout_into_record_json(
    raw_value: str,
    state_key: str,
    visible_session_keys: set[str],
    assignments: dict[str, str],
    order_data: dict[str, list[str]],
    group_labels: dict[str, str] | None,
) -> str | None:
    try:
        data = json.loads(raw_value.lstrip("﻿\x00\x01"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    state = data.get(state_key)
    if not isinstance(state, dict):
        return None

    existing_assignments = _string_dict(state.get("customGroupAssignments"))
    for session_key in visible_session_keys:
        existing_assignments.pop(session_key, None)
    existing_assignments.update(assignments)
    state["customGroupAssignments"] = existing_assignments

    existing_order = _list_dict(state.get("customGroupOrder"))
    cleaned_order: dict[str, list[str]] = {}
    for group_id, session_keys in existing_order.items():
        cleaned_order[group_id] = [
            session_key for session_key in session_keys if session_key not in visible_session_keys
        ]
    for group_id, session_keys in order_data.items():
        cleaned_order[group_id] = list(session_keys)
    state["customGroupOrder"] = cleaned_order

    if group_labels:
        existing_labels = _custom_group_labels(state.get("customGroups"))
        existing_labels.update(group_labels)
        state["customGroups"] = [
            {"id": group_id, "name": name} for group_id, name in existing_labels.items()
        ]

    # The sidebar only renders the grouped view when groupByByMode.code is
    # "custom" — with groups present but the switch unset, everything shows
    # flat under Recents. Flip it when we deliver groups, but never override
    # an explicit user choice.
    if state_key == "state" and (group_labels or order_data):
        group_by = state.get("groupByByMode")
        if not isinstance(group_by, dict):
            group_by = {}
        if not group_by.get("code"):
            group_by["code"] = "custom"
            state["groupByByMode"] = group_by

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _merge_slices(desktop_slice: dict[str, object], local_storage_slice: dict[str, object]) -> dict[str, object]:
    desktop_assignments = _string_dict(desktop_slice.get("customGroupAssignments"))
    local_assignments = _string_dict(local_storage_slice.get("customGroupAssignments"))
    desktop_order = _list_dict(desktop_slice.get("customGroupOrder"))
    local_order = _list_dict(local_storage_slice.get("customGroupOrder"))
    labels: dict[str, str] = {}
    labels.update(_custom_group_labels(local_storage_slice.get("customGroups")))
    labels.update(_custom_group_labels(desktop_slice.get("customGroups")))

    assignments = desktop_assignments if desktop_assignments else local_assignments
    order_data = desktop_order if desktop_order else local_order

    return {
        "customGroupAssignments": assignments,
        "customGroupOrder": {group_id: list(session_keys) for group_id, session_keys in order_data.items()},
        "customGroups": [{"id": group_id, "name": label} for group_id, label in labels.items()],
    }


def _ensure_dict(parent: dict[str, object], key: str) -> dict[str, object]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _read_desktop_config(config_path: Path) -> dict[str, object]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_desktop_config_strict(config_path: Path) -> dict[str, object]:
    """Read the desktop config for a rewrite.

    Unlike the scan-path reader, a config file that exists but cannot be parsed
    must abort the save: silently rebuilding from an empty dict would wipe every
    other preference (MCP servers, etc.) stored in the same file.
    """
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Claude desktop config is not a JSON object: {config_path}")
    return data


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    tmp_path = path.parent / f"{path.name}.tmp-write"
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _read_desktop_slice(config_path: Path) -> dict[str, object]:
    data = _read_desktop_config(config_path)
    slice_data = (
        data.get("preferences", {})
        .get("epitaxyPrefs", {})
        .get("dframe-local-slice", {})
    )
    return slice_data if isinstance(slice_data, dict) else {}


def _read_local_storage_slice(leveldb_root: Path) -> dict[str, object]:
    if not leveldb_root.exists():
        return {}
    try:
        from chromium_reader import LocalStorageReader
    except ImportError:
        return {}

    best_slice: dict[str, object] = {}
    best_score = 0
    reader = LocalStorageReader(leveldb_root)
    try:
        for record in reader.records(include_deletions=False):
            # The claude.ai client stores under https://claude.ai; gateway
            # builds (Claude-3p) store under app://localhost. Accept any
            # origin that carries a dframe record.
            script_key = str(getattr(record, "script_key", ""))
            value = getattr(record, "value", "")
            slice_data = _slice_from_local_storage_record(script_key, value)
            score = _slice_score(slice_data)
            if score > best_score:
                best_slice = slice_data
                best_score = score
    except Exception:
        return best_slice
    finally:
        reader.close()
    return best_slice


def _slice_from_local_storage_record(script_key: str, raw_value: object) -> dict[str, object]:
    if not isinstance(raw_value, str):
        return {}
    try:
        data = json.loads(raw_value.lstrip("\ufeff\x00\x01"))
    except json.JSONDecodeError:
        return {}
    if script_key == "dframe-store":
        state = data.get("state") if isinstance(data, dict) else None
        return state if isinstance(state, dict) else {}
    if script_key == "LSS-persisted.dframe-local-slice":
        value = data.get("value") if isinstance(data, dict) else None
        return value if isinstance(value, dict) else {}
    return {}


def _slice_score(slice_data: dict[str, object]) -> int:
    return (
        len(_custom_group_labels(slice_data.get("customGroups"))) * 3
        + len(_string_dict(slice_data.get("customGroupAssignments"))) * 2
        + len(_list_dict(slice_data.get("customGroupOrder")))
    )


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): raw_value
        for key, raw_value in value.items()
        if isinstance(raw_value, str) and isinstance(key, str)
    }


def _list_dict(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, raw_items in value.items():
        if not isinstance(key, str) or not isinstance(raw_items, list):
            continue
        result[key] = tuple(item for item in raw_items if isinstance(item, str))
    return result


def _custom_group_labels(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    labels: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        group_id = item.get("id")
        name = item.get("name")
        if isinstance(group_id, str) and isinstance(name, str) and name.strip():
            labels[group_id] = name.strip()
    return labels


def _code_key(session_id: str) -> str:
    return f"code:{session_id}"
