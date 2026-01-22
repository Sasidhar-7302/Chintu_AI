# Chintu Personal AI Assistant - Launcher
# This script starts both the Python backend and Flutter UI

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Chintu Personal AI Assistant" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Get the script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Check if virtual environment exists
if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Error: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Run: python -m venv venv" -ForegroundColor Yellow
    exit 1
}

# Start Chintu (Backend + UI)
Write-Host "Starting Chintu Assistant..." -ForegroundColor Green
$pythonPath = Join-Path $scriptDir "venv\Scripts\python.exe"
$runnerScript = Join-Path $scriptDir "run_chintu.py"

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$scriptDir'; & '$pythonPath' '$runnerScript' --with-ui"

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "Services starting..." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
