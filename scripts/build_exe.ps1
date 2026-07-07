$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

# We only use QtCore / QtGui / QtWidgets. PyInstaller's PySide6 hook follows
# the actual imports, so we must NOT use --collect-all (it dragged the entire
# 642 MB Qt tree — WebEngine, Qml, Quick, 3D, Charts … — into the exe). We
# additionally exclude the heavy Qt submodules that hooks might otherwise pull
# transitively, cutting the onefile from ~245 MB to a fraction and speeding up
# the extract-on-launch startup.
$Excludes = @(
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngine", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtWebView", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtSpatialAudio",
    "PySide6.QtNetworkAuth", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtConcurrent", "PySide6.QtDBus",
    "PySide6.QtHttpServer", "PySide6.QtTextToSpeech",
    # unrelated heavy stdlib/third-party that PyInstaller may probe
    "tkinter", "numpy", "pandas", "matplotlib", "PIL", "pytest"
)

$Args = @(
    "-m", "PyInstaller",
    "--name", "cc-code-history-tidy",
    "--windowed",
    "--onefile",
    "--clean",
    "--noconfirm",
    "--collect-submodules", "chromium_reader"
)
foreach ($mod in $Excludes) {
    $Args += @("--exclude-module", $mod)
}
$Args += "cc_history_tidy\main.py"

& $Python @Args
