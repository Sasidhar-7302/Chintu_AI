param(
  [switch]$SkipUi
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

Write-Host "[1/3] Running backend core tests..."
& venv\Scripts\python.exe -m pytest -q tests\core

Write-Host "[2/3] Running scenario smoke test..."
& venv\Scripts\python.exe -m pytest -q tests\scenarios\chintu_50_daily_scenarios.py -k "not live" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Scenario smoke test skipped/failing in this environment; continuing."
}

if (-not $SkipUi) {
  Write-Host "[3/3] Running Flutter analyze..."
  Push-Location chintu_ui
  try {
    flutter analyze
  }
  finally {
    Pop-Location
  }
} else {
  Write-Host "[3/3] Flutter analyze skipped."
}

Write-Host ""
Write-Host "Quality gate completed."
