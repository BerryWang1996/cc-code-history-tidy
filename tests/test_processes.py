from cc_history_tidy.processes import (
    claude_desktop_running_from_paths,
    is_claude_desktop_path,
    is_claude_desktop_running,
)

MSIX_DESKTOP = r"C:\Program Files\WindowsApps\Claude_1.18286.0.0_x64__pzs8sxrjxfjjc\app\Claude.exe"
ELECTRON_DESKTOP = r"C:\Users\me\AppData\Local\Claude\app-0.1.2\Claude.exe"
GATEWAY_CLI = r"C:\Users\me\AppData\Local\Claude-3p\claude-code\2.1.197\claude.exe"
UNRELATED = r"C:\Windows\notepad.exe"


def test_desktop_paths_are_recognized():
    assert is_claude_desktop_path(MSIX_DESKTOP)
    assert is_claude_desktop_path(ELECTRON_DESKTOP)


def test_cli_path_is_not_desktop():
    # The Claude Code CLI lives under a claude-code directory and must not
    # block Execute.
    assert not is_claude_desktop_path(GATEWAY_CLI)


def test_unrelated_process_is_not_desktop():
    assert not is_claude_desktop_path(UNRELATED)


def test_unresolvable_path_fails_safe_as_desktop():
    # A claude.exe whose path we couldn't read is assumed to be Desktop so we
    # never write while it might be open.
    assert is_claude_desktop_path("")


def test_running_true_when_any_desktop_path_present():
    assert claude_desktop_running_from_paths([GATEWAY_CLI, MSIX_DESKTOP])


def test_running_false_when_only_cli():
    assert not claude_desktop_running_from_paths([GATEWAY_CLI, GATEWAY_CLI])


def test_running_false_when_no_claude():
    assert not claude_desktop_running_from_paths([])


def test_injected_paths_bypass_enumeration():
    assert is_claude_desktop_running(image_paths=[MSIX_DESKTOP]) is True
    assert is_claude_desktop_running(image_paths=[GATEWAY_CLI]) is False
