$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "chintu_gateway.pid"

if (-not (Test-Path $pidFile)) {
  Write-Output "No gateway PID file found."
  exit 0
}

$pid = Get-Content -Path $pidFile | Select-Object -First 1
if ($pid) {
  try {
    Stop-Process -Id $pid -Force
    Write-Output "Gateway stopped (PID: $pid)"
  } catch {
    Write-Output "Failed to stop PID $pid: $($_.Exception.Message)"
  }
}

Remove-Item -Path $pidFile -Force
