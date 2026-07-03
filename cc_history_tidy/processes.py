from __future__ import annotations

import os
import subprocess


CLAUDE_PROCESS_NAMES = (
    "claude.exe",
    "claude desktop.exe",
    "claude-desktop.exe",
)


def tasklist_contains_claude(tasklist_output: str) -> bool:
    lowered = tasklist_output.lower()
    return any(process_name in lowered for process_name in CLAUDE_PROCESS_NAMES)


def is_claude_desktop_running() -> bool:
    if os.name != "nt":
        return False
    kwargs = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    completed = subprocess.run(
        ["tasklist"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        **kwargs,
    )
    return tasklist_contains_claude(completed.stdout)
