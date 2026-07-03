import json

import pytest

from cc_history_tidy.code_groups import save_code_group_layout_to_desktop_config


def test_save_raises_when_existing_config_is_unreadable(tmp_path):
    """A corrupt config must abort the save instead of being rebuilt from empty,
    which would wipe every other preference stored in the same file."""
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        save_code_group_layout_to_desktop_config(
            config_path,
            visible_session_keys={"code:s1"},
            assignments={"code:s1": "cg-a"},
            order_data={"cg-a": ["code:s1"]},
        )

    assert config_path.read_text(encoding="utf-8") == "{ not valid json"


def test_save_preserves_unrelated_config_keys(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {"example": {"command": "example.exe"}},
                "coworkUserFilesPath": "C:/cowork",
                "preferences": {
                    "epitaxyPrefs": {
                        "dframe-local-slice": {
                            "pinnedOrder": ["code:s9"],
                            "customGroupAssignments": {"code:old": "cg-old"},
                            "customGroupOrder": {"cg-old": ["code:old"]},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    save_code_group_layout_to_desktop_config(
        config_path,
        visible_session_keys={"code:s1"},
        assignments={"code:s1": "cg-a"},
        order_data={"cg-a": ["code:s1"]},
    )

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["mcpServers"] == {"example": {"command": "example.exe"}}
    assert data["coworkUserFilesPath"] == "C:/cowork"
    slice_data = data["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    assert slice_data["pinnedOrder"] == ["code:s9"]
    # Non-visible existing assignments survive; visible ones are replaced.
    assert slice_data["customGroupAssignments"] == {"code:old": "cg-old", "code:s1": "cg-a"}
    assert slice_data["customGroupOrder"]["cg-a"] == ["code:s1"]


def test_save_creates_config_when_missing(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"

    save_code_group_layout_to_desktop_config(
        config_path,
        visible_session_keys=set(),
        assignments={"code:s1": "cg-a"},
        order_data={"cg-a": ["code:s1"]},
    )

    data = json.loads(config_path.read_text(encoding="utf-8"))
    slice_data = data["preferences"]["epitaxyPrefs"]["dframe-local-slice"]
    assert slice_data["customGroupAssignments"] == {"code:s1": "cg-a"}
