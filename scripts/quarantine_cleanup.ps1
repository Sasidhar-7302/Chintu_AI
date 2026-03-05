$ErrorActionPreference = "Stop"

function New-Stamp {
  return (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
}

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function Move-ToQuarantine([string]$SourcePath, [string]$QuarantineDir, [ref]$Moved) {
  if (-not (Test-Path -LiteralPath $SourcePath)) {
    return
  }
  $name = Split-Path -Leaf $SourcePath
  $dest = Join-Path $QuarantineDir $name
  $i = 1
  while (Test-Path -LiteralPath $dest) {
    $dest = Join-Path $QuarantineDir ("{0}_{1}" -f $name, $i)
    $i++
  }
  try {
    Move-Item -LiteralPath $SourcePath -Destination $dest -Force
    $Moved.Value += @(@{
      source = $SourcePath
      dest   = $dest
    })
  } catch {
    Write-Warning ("Failed to move '{0}' to quarantine: {1}" -f $SourcePath, $_.Exception.Message)
  }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stamp = New-Stamp

$verifyDeleteRoot = Join-Path $env:USERPROFILE ".chintu\verify_delete"
$quarantineDir = Join-Path $verifyDeleteRoot ("repo_cleanup_{0}" -f $stamp)

Ensure-Dir $verifyDeleteRoot
Ensure-Dir $quarantineDir

$moved = @()

Push-Location $repoRoot
try {
  Move-ToQuarantine ".claude" $quarantineDir ([ref]$moved)
  Move-ToQuarantine ".GCC" $quarantineDir ([ref]$moved)
  Move-ToQuarantine ".pytest_cache" $quarantineDir ([ref]$moved)
  Move-ToQuarantine ".tmp" $quarantineDir ([ref]$moved)
  Move-ToQuarantine "generated_reports" $quarantineDir ([ref]$moved)
} finally {
  Pop-Location
}

$manifest = @{
  repo_root = $repoRoot
  quarantine_dir = $quarantineDir
  moved = $moved
  created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
}

$manifestPath = Join-Path $quarantineDir "manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Out-File -FilePath $manifestPath -Encoding utf8

Write-Host ("Quarantine cleanup complete. Quarantine dir: {0}" -f $quarantineDir)
Write-Host ("Manifest: {0}" -f $manifestPath)
if ($moved.Count -eq 0) {
  Write-Host "Nothing to move."
} else {
  Write-Host "Moved:"
  $moved | ForEach-Object { Write-Host ("- {0} -> {1}" -f $_.source, $_.dest) }
}

