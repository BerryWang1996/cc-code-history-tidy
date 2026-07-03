# CC Code History Tidy

A Windows desktop utility for migrating Claude Desktop Code-mode conversation
metadata between local Claude account partitions.

## Safety Model

The app migrates Claude Desktop Code session metadata only. It does not edit
OAuth credentials, token files, `.credentials.json`, or JSONL transcript bodies
under `~/.claude/projects`.

Every migration creates a full snapshot of the detected `claude-code-sessions`
directory before writing. Copy mode keeps source metadata. Move mode performs a
safe move: backup, copy, verify copied metadata, then remove the source metadata.

Claude Desktop must be closed before a migration can run. Scanning is allowed
while Claude is open.

## Path Discovery

The app does not hard-code a user name. It discovers paths from:

- `%USERPROFILE%\.claude.json`
- `%USERPROFILE%\.claude\projects`
- `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code-sessions`
- `%APPDATA%\Claude\claude-code-sessions`
- `%LOCALAPPDATA%\Claude\claude-code-sessions`
- `%LOCALAPPDATA%\Claude-3p\claude-code-sessions`

If multiple Claude Desktop roots are found, the root containing the current
`oauthAccount.accountUuid` is preferred.

## Account Label Config

Accounts are identified by Claude account UUIDs, but the UI can display friendly
account labels from:

`%USERPROFILE%\.claude-desktop-migrator\account-groups.json`

Example:

```json
{
  "accounts": {
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa": {
      "label": "Current Work"
    },
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb": {
      "label": "Old Personal"
    }
  }
}
```

Unconfigured accounts are shown with an anonymized hash label.

## Claude Code Groups

Claude Desktop Code stores sessions as:

`claude-code-sessions\<accountUuid>\<groupUuid>\<session>.json`

The app displays this as:

`Account -> Code group -> Conversation`

The UI is a single editable tree. Drag Code groups or conversations to stage a
new position. These edits do not touch disk until `Execute` is pressed. If
Claude Desktop / Claude Code Desktop is running, `Execute` is disabled and the
tooltip asks you to close the client first.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -v
```

## Build

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

The executable is written to `dist\cc-code-history-tidy.exe`.
