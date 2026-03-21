$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$entryScript = Join-Path $projectRoot "backend\server.py"
$buildRoot = Join-Path $projectRoot "build\backend"
$distPath = Join-Path $buildRoot "dist"
$workPath = Join-Path $buildRoot "work"
$specPath = Join-Path $buildRoot "spec"
$showcaseCachePath = Join-Path $projectRoot "backend\showcase_cache"

if (-not (Test-Path $showcaseCachePath)) {
    New-Item -ItemType Directory -Path $showcaseCachePath | Out-Null
}

Write-Host "Building Python backend from $entryScript"

pyinstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name OpenClawBackend `
    --distpath $distPath `
    --workpath $workPath `
    --specpath $specPath `
    --add-data "$showcaseCachePath;showcase_cache" `
    --exclude-module PyQt5 `
    --exclude-module PySide6 `
    --exclude-module tkinter `
    $entryScript
