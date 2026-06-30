# Task Scheduler example:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\vrcx2trakt\scripts\auto_sync.ps1"
# Run `vrcx2trakt setup` and `vrcx2trakt login` once before scheduling.

$ErrorActionPreference = 'Stop'

$command = Get-Command vrcx2trakt -ErrorAction SilentlyContinue
if ($command) {
    $exe = $command.Source
    $arguments = @('sync')
} else {
    $exe = 'python'
    $arguments = @('-m', 'vrcx2trakt', 'sync')
}

if ($env:VRCX2TRAKT_STATE_DIR) {
    $stateDir = $env:VRCX2TRAKT_STATE_DIR
} elseif ($env:LOCALAPPDATA) {
    $stateDir = Join-Path $env:LOCALAPPDATA 'vrcx2trakt'
} else {
    $stateDir = Join-Path $HOME 'AppData\Local\vrcx2trakt'
}

$logDir = Join-Path $stateDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$logFile = Join-Path $logDir "sync-$timestamp.log"

"[$((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))] Starting vrcx2trakt sync" | Tee-Object -FilePath $logFile
"Command: $exe $($arguments -join ' ')" | Tee-Object -FilePath $logFile -Append
"If this fails with an authorisation error, run: vrcx2trakt setup; vrcx2trakt login" | Tee-Object -FilePath $logFile -Append
"" | Tee-Object -FilePath $logFile -Append

& $exe @arguments 2>&1 | Tee-Object -FilePath $logFile -Append
$status = if ($LASTEXITCODE -ne $null) { $LASTEXITCODE } else { 0 }

if ($status -ne 0) {
    Write-Error "vrcx2trakt sync failed with exit code $status. Log: $logFile"
    exit $status
}

Write-Host "vrcx2trakt sync completed. Log: $logFile"
