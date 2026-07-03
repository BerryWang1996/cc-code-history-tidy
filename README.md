# CC Code History Tidy

A Windows desktop utility for migrating Claude Desktop Code-mode conversation
metadata between local Claude account partitions.

## Safety Model

The app migrates Claude Desktop Code session metadata only. It does not edit
OAuth credentials, token files, `.credentials.json`, or JSONL transcript bodies
under `~/.claude/projects`.

Every execution creates a full snapshot of **every** `claude-code-sessions`
root involved (source roots, target roots, and each root's
`claude_desktop_config.json`) before writing. If any step fails, all involved
roots are rolled back from those snapshots. Move mode performs a safe move:
backup, copy, verify copied metadata, remove the source metadata, then prune
emptied directories.

Copy mode keeps the source metadata and writes the duplicate with a **new
`sessionId`** (and a matching filename when the file follows the
`<sessionId>.json` convention). This is required because Claude Desktop keys
custom-group assignments by `code:<sessionId>` per install root — two files
sharing one id would collide. The copy references the same CLI transcript and
starts out ungrouped.

Claude Desktop must be closed before a migration can run. Scanning is allowed
while Claude is open. Note: the Claude Code CLI also runs as `claude.exe` on
Windows, so the running-process check triggers while any CLI session is open.

### Known limitation: sidebar group layout lives in three stores

Claude Desktop persists custom Code-group layout in
`claude_desktop_config.json` **and** in the renderer's Local Storage
(LevelDB: the `dframe-store` record, which also holds the group *names*, and
`LSS-persisted.dframe-local-slice`). This tool reads all of them but can only
safely write `claude_desktop_config.json` — LevelDB cannot be edited while
guaranteeing integrity. If Claude Desktop rehydrates the layout from its Local
Storage copy on next launch, staged regrouping done in this tool may be
reverted. Verify the sidebar after restarting Claude Desktop; the session
*files* themselves are unaffected by this caveat.

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

Only dragging a conversation to a **different account** (or the same account in
a different Claude install root) moves metadata files on disk. Regrouping
between Code groups within an account is a layout-only change written to that
root's `claude_desktop_config.json`; group layout for each install root is
written to that root's own config file.

If the same account is signed into several Claude installs, its tree items are
suffixed with the install root name (e.g. `[Claude-3p]`) so they can be told
apart.

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
