"""Detect whether Claude Desktop is running.

Claude Desktop and the Claude Code CLI both run as ``claude.exe`` on Windows,
so a name-only check (tasklist) cannot tell them apart, and the LevelDB LOCK
file is unreliable — the MSIX Claude Desktop is suspended in the background and
releases its locks. We therefore enumerate running processes and classify by
**image path**: a ``claude.exe`` whose path is not inside a ``claude-code``
directory is the desktop app; the CLI always lives under ``claude-code``.

Enumeration uses the Win32 ToolHelp + QueryFullProcessImageName APIs via
``ctypes`` — no subprocess spawn (fast enough for a 2 s UI poll) and no extra
dependency.
"""

from __future__ import annotations

import os

_DESKTOP_EXE = "claude.exe"
_CLI_MARKER = "claude-code"


def is_claude_desktop_path(image_path: str) -> bool:
    """True if an executable path is Claude Desktop (not the Claude Code CLI)."""
    if not image_path:
        # A claude.exe whose path we could not resolve: assume Desktop so we
        # fail safe (blocking Execute) rather than risk writing under it.
        return True
    normalized = image_path.replace("\\", "/").lower()
    if not normalized.endswith("/" + _DESKTOP_EXE) and not normalized.endswith(_DESKTOP_EXE):
        return False
    return _CLI_MARKER not in normalized


def claude_desktop_running_from_paths(image_paths: list[str]) -> bool:
    return any(is_claude_desktop_path(path) for path in image_paths)


def _iter_claude_process_paths() -> list[str]:
    """Full image paths of every running ``claude.exe`` process (Windows)."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    TH32CS_SNAPPROCESS = 0x2
    INVALID_HANDLE = ctypes.c_void_p(-1).value
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE:
        return []

    pids: list[int] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            if entry.szExeFile.lower() == _DESKTOP_EXE:
                pids.append(int(entry.th32ProcessID))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)

    paths: list[str] = []
    for pid in pids:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            paths.append("")  # can't resolve → treated as Desktop (fail safe)
            continue
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                paths.append(buffer.value)
            else:
                paths.append("")
        finally:
            kernel32.CloseHandle(handle)
    return paths


def is_claude_desktop_running(image_paths: list[str] | None = None) -> bool:
    if image_paths is not None:
        return claude_desktop_running_from_paths(image_paths)
    if os.name != "nt":
        return False
    try:
        return claude_desktop_running_from_paths(_iter_claude_process_paths())
    except OSError:  # pragma: no cover - Win32 API failure
        # If enumeration fails, fail safe: assume Desktop may be running.
        return True
