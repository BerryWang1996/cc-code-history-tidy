$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

& $Python -m PyInstaller `
    --name cc-code-history-tidy `
    --windowed `
    --onefile `
    --clean `
    --noconfirm `
    --collect-all PySide6 `
    --collect-all chromium_reader `
    cc_history_tidy\main.py
