$ErrorActionPreference = "Stop"

function Resolve-Python {
  $venvPy = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"
  $venvPy = (Resolve-Path $venvPy -ErrorAction SilentlyContinue)
  if ($venvPy) { return $venvPy.Path }
  return "python"
}

function Invoke-Gate {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][scriptblock]$Runner
  )
  Write-Host ("`n=== {0} ===" -f $Name)
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $global:LASTEXITCODE = 0
  & $Runner
  if ($LASTEXITCODE -ne 0) {
    throw ("Gate failed: {0} (exit code {1})" -f $Name, $LASTEXITCODE)
  }
  $sw.Stop()
  Write-Host ("PASS {0} ({1:n1}s)" -f $Name, $sw.Elapsed.TotalSeconds)
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
  $python = Resolve-Python
  Write-Host ("Using Python: {0}" -f $python)

  Invoke-Gate -Name "pytest" -Runner { & $python -m pytest -q }
  Invoke-Gate -Name "docs_check" -Runner { & $python scripts/docs_check.py }
  Invoke-Gate -Name "doctor" -Runner { & $python scripts/chintu_doctor.py }
  Invoke-Gate -Name "benchmark_dry_allow_skips" -Runner {
    & $python scripts/chintu_50_realistic_benchmark.py `
      --allow-skips `
      --verify-side-effects `
      --scenarios tests/scenarios/chintu_50_personal_daily.py `
      --out-dir generated_reports
  }

  Write-Host "`nAll quality gates passed."
} finally {
  Pop-Location
}
