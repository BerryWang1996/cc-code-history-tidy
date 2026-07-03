from types import SimpleNamespace

from cc_history_tidy import processes
from cc_history_tidy.processes import is_claude_desktop_running, tasklist_contains_claude


def test_tasklist_parser_detects_claude_process():
    output = "Claude.exe                    1234 Console                    1     42,000 K"

    assert tasklist_contains_claude(output)


def test_tasklist_parser_ignores_unrelated_processes():
    output = "notepad.exe                  1234 Console                    1     42,000 K"

    assert not tasklist_contains_claude(output)


def test_tasklist_process_is_started_without_console_window(monkeypatch):
    calls = {}

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(processes.subprocess, "run", fake_run)
    monkeypatch.setattr(processes.os, "name", "nt")

    assert not is_claude_desktop_running()
    assert calls["args"] == ["tasklist"]
    assert calls["kwargs"]["creationflags"] & processes.subprocess.CREATE_NO_WINDOW
