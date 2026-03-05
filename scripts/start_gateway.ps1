$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "chintu_gateway.pid"

if (Test-Path $pidFile) {
  Write-Output "Gateway PID file already exists at $pidFile. Stop it first."
  exit 0
}

$python = (Get-Command python).Source
if (-not $python) {
  Write-Error "Python not found in PATH."
  exit 1
}

$proc = Start-Process -FilePath $python -ArgumentList "-m", "chintu_backend.gateway.server" -WorkingDirectory $root -PassThru -WindowStyle Hidden
Set-Content -Path $pidFile -Value $proc.Id
Write-Output "Gateway started (PID: $($proc.Id))"
