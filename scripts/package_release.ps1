param(
  [string]$Version = "",
  [string]$OutputRoot = "dist"
)

$ErrorActionPreference = "Stop"

function New-CleanDirectory {
  param([string]$Path)
  if (Test-Path $Path) {
    Remove-Item -Path $Path -Recurse -Force
  }
  New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ([string]::IsNullOrWhiteSpace($Version)) {
  $releaseName = "chintu_release_$timestamp"
} else {
  $safeVersion = ($Version -replace "[^a-zA-Z0-9._-]", "_")
  $releaseName = "chintu_release_$safeVersion"
}

$outputRootPath = Join-Path $projectRoot $OutputRoot
New-Item -ItemType Directory -Path $outputRootPath -Force | Out-Null

$stagingDir = Join-Path $outputRootPath $releaseName
$zipPath = Join-Path $outputRootPath "$releaseName.zip"
New-CleanDirectory -Path $stagingDir
if (Test-Path $zipPath) {
  Remove-Item -Path $zipPath -Force
}

Write-Host "[1/5] Building release staging at $stagingDir"

# Core runtime
Copy-Item -Path "chintu_backend" -Destination $stagingDir -Recurse -Force
Copy-Item -Path "chintu_ui" -Destination $stagingDir -Recurse -Force
Copy-Item -Path "skills" -Destination $stagingDir -Recurse -Force
Copy-Item -Path "docs" -Destination $stagingDir -Recurse -Force

# Required root files
Copy-Item -Path "README.md" -Destination $stagingDir -Force
Copy-Item -Path "requirements.txt" -Destination $stagingDir -Force
Copy-Item -Path ".env.example" -Destination $stagingDir -Force
if (Test-Path "pytest.ini") {
  Copy-Item -Path "pytest.ini" -Destination $stagingDir -Force
}

Write-Host "[2/5] Copying launcher and ops scripts"
$scriptsOut = Join-Path $stagingDir "scripts"
New-Item -ItemType Directory -Path $scriptsOut -Force | Out-Null
$releaseScripts = @(
  "start_chintu.bat",
  "setup_env.bat",
  "install.py",
  "chintu_cli.py",
  "chintu_doctor.py",
  "check_deps.py",
  "ensure_docker.py",
  "install_ffmpeg.py",
  "run_voice_client.py",
  "start_voice_client.bat",
  "Launch-Chintu.ps1",
  "Launch-Chintu.vbs"
)
foreach ($scriptName in $releaseScripts) {
  $source = Join-Path "scripts" $scriptName
  if (Test-Path $source) {
    Copy-Item -Path $source -Destination $scriptsOut -Force
  }
}

Write-Host "[3/5] Removing local-only artifacts from release"
$prunePaths = @(
  ".git",
  "venv",
  "logs",
  "generated_reports",
  "data",
  ".pytest_cache",
  "chintu_ui/.idea",
  "chintu_ui/.dart_tool",
  "chintu_ui/build",
  "chintu_ui/.flutter-plugins",
  "chintu_ui/.flutter-plugins-dependencies",
  "chintu_ui/.metadata",
  "chintu_ui/chintu_ui.iml"
)
foreach ($relative in $prunePaths) {
  $target = Join-Path $stagingDir $relative
  if (Test-Path $target) {
    Remove-Item -Path $target -Recurse -Force
  }
}

Write-Host "[4/5] Writing release manifest"
$manifestPath = Join-Path $stagingDir "RELEASE_MANIFEST.txt"
$manifest = @(
  "Chintu Release Manifest",
  "Generated: $(Get-Date -Format o)",
  "Version: $($Version.Trim())",
  "Package: $releaseName",
  "",
  "Startup:",
  "  scripts\\setup_env.bat",
  "  scripts\\start_chintu.bat",
  "",
  "Security:",
  "  - Keep .env local, never commit secrets",
  "  - Rotate Telegram/API tokens before distribution"
)
$manifest | Set-Content -Path $manifestPath -Encoding UTF8

Write-Host "[5/5] Creating zip package"
Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Release package created:"
Write-Host "  Staging: $stagingDir"
Write-Host "  Zip:     $zipPath"
