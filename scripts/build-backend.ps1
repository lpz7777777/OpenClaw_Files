$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$entryScript = Join-Path $projectRoot "backend\server.py"
$buildRoot = Join-Path $projectRoot "build\backend"
$distPath = Join-Path $buildRoot "dist"
$workPath = Join-Path $buildRoot "work"
$specPath = Join-Path $buildRoot "spec"

Write-Host "Building Python backend from $entryScript"

pyinstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name OpenClawBackend `
    --distpath $distPath `
    --workpath $workPath `
    --specpath $specPath `
    --exclude-module PyQt5 `
    --exclude-module PySide6 `
    --exclude-module tkinter `
    $entryScript
