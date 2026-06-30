Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Build both Windows EXE artefacts from a local checkout.
# Run this script from anywhere on a Windows machine with Python available.

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPath = Join-Path $RepoRoot ".venv-build"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$PyInstallerExe = Join-Path $VenvPath "Scripts\pyinstaller.exe"

Set-Location $RepoRoot

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating build virtual environment at $VenvPath"
    py -3 -m venv $VenvPath
}

Write-Host "Installing project and PyInstaller"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install . pyinstaller

Write-Host "Building console EXE"
& $PyInstallerExe --clean --noconfirm packaging/vrcx2trakt-cli.spec

Write-Host "Building windowed GUI EXE"
& $PyInstallerExe --clean --noconfirm packaging/vrcx2trakt-gui.spec

Write-Host "Built artefacts:"
Write-Host " - $(Join-Path $RepoRoot 'dist\vrcx2trakt.exe')"
Write-Host " - $(Join-Path $RepoRoot 'dist\vrcx2trakt-gui.exe')"
