import json
import subprocess

from cc_history_tidy.paths import discover_claude_environment
from cc_history_tidy.session_tree import format_activity_timestamp
from tests.fixtures import build_claude_fixture


def test_format_activity_timestamp_renders_readable_datetime():
    text = format_activity_timestamp(1782521165394)
    assert text.startswith("20")
    assert "-" in text and ":" in text
    assert format_activity_timestamp(None) == ""
    assert format_activity_timestamp(0) == ""


def test_junctioned_session_roots_are_deduplicated(tmp_path):
    """%APPDATA%/Claude can be a junction into the MSIX LocalCache dir; the
    same physical store must not be scanned as two roots."""
    fixture = build_claude_fixture(tmp_path)
    msix_claude_root = fixture.sessions_root.parent
    junction = fixture.appdata / "Claude"
    junction.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(msix_claude_root)],
        capture_output=True,
    )
    if result.returncode != 0:
        import pytest

        pytest.skip("cannot create junction on this filesystem")

    env = discover_claude_environment(
        fixture.user_profile,
        fixture.appdata,
        fixture.localappdata,
    )

    assert len(env.sessions_roots) == 1
