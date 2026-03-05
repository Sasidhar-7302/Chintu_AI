@echo off
setlocal EnableDelayedExpansion
echo ============================================
echo    Chintu Personal AI Assistant (Fixed)
echo ============================================
echo.

REM Navigate to Project Root (parent of scripts/)
pushd "%~dp0.." || (
    echo Error: Could not change to project root.
    pause
    exit /b 1
)

set "VENV_PYTHON=venv\Scripts\python.exe"
set "SCRIPTS_DIR=scripts"

echo Working Directory: %CD%

REM Check if virtual environment exists
if not exist "%VENV_PYTHON%" (
    echo Error: Virtual environment not found at %VENV_PYTHON%
    echo Run: python -m venv venv
    pause
    exit /b 1
)

REM Check System Health and Dependencies
echo Checking Docker Status...
"%VENV_PYTHON%" "%SCRIPTS_DIR%\ensure_docker.py"

echo Running Pre-flight Checks...
"%VENV_PYTHON%" "%SCRIPTS_DIR%\check_deps.py"
if %errorlevel% equ 3 (
    echo [INFO] FFmpeg not found
    echo [INFO] FFmpeg missing. Attempting automatic installation...
    "%VENV_PYTHON%" "%SCRIPTS_DIR%\install_ffmpeg.py"
    if %errorlevel% neq 0 (
        echo [ERROR] FFmpeg install failed.
        pause
        exit /b 1
    )
    REM Re-run check
    "%VENV_PYTHON%" "%SCRIPTS_DIR%\check_deps.py"
)
if %errorlevel% equ 2 (
    echo [ERROR] System Check Failed
    echo [ERROR] STOPPING: Critical system requirements missing.
    echo Please read the error messages above - e.g. missing FFmpeg or Microphone.
    pause
    exit /b 1
)
if %errorlevel% equ 1 (
    echo Found missing or outdated dependencies. Installing...
    venv\Scripts\pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo Error installing dependencies!
        pause
        exit /b 1
    )
    REM Re-run check
    "%VENV_PYTHON%" "%SCRIPTS_DIR%\check_deps.py"
)

echo Dependencies satisfied.

REM Start Python backend FIRST in background
echo Starting Chintu Backend...

REM Clean up any stale backend processes
taskkill /F /FI "WINDOWTITLE eq Chintu Backend" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765.*LISTENING"') do (
    echo Killing stale process on port 8765: %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
for /f "usebackq delims=" %%T in (`powershell -NonInteractive -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set "TS=%%T"
set "BACKEND_LOG=%LOG_DIR%\backend_%TS%.log"
set "BACKEND_LATEST=%LOG_DIR%\backend_latest.log"

REM Launch Backend
start "Chintu Backend" powershell -NoExit -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; & '%VENV_PYTHON%' -u -m chintu_backend 2>&1 | Tee-Object -FilePath '%BACKEND_LOG%' | Tee-Object -FilePath '%BACKEND_LATEST%'"

REM Wait for backend
echo Waiting for backend to initialize...
set /a count=0
:waitloop
timeout /t 3 /nobreak >nul
set /a count+=1
netstat -an | find ":8765" | find "LISTENING" >nul
if %errorlevel% equ 0 (
    echo Backend ready on port 8765!
    goto :startui
)
if %count% geq 20 (
    echo WARNING: Backend readiness confirmation timed out. Continuing...
    goto :startui
)
echo    Waiting... (%count%/20)
goto :waitloop

:startui
echo Launching UI...

REM 1. Check for pre-built Windows Executable
set "UI_EXE=chintu_ui\build\windows\x64\runner\Release\chintu_ui.exe"
if exist "%UI_EXE%" (
    echo [INFO] Found pre-built Chintu UI.
    echo Launching: %UI_EXE%
    start "Chintu UI" "%UI_EXE%"
    goto :success_msg
)

REM 2. Fallback to Flutter Tool
echo [INFO] Pre-built UI not found. Checking for Flutter SDK...
where flutter >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Flutter not found in PATH and no binary found.
    echo UI cannot be launched.
    
    echo NOTE: The Backend is running. You can use Voice commands.
    echo Press any key to exit launcher.
    pause
    exit /b 0
)

echo Launching Flutter UI (Debug Mode)...
set "UI_LOG=%LOG_DIR%\ui_%TS%.log"
set "UI_LATEST=%LOG_DIR%\ui_latest.log"
start "Chintu UI" powershell -NoExit -NoProfile -Command "Set-Location 'chintu_ui'; & flutter run -d windows 2>&1 | Tee-Object -FilePath '%UI_LOG%' | Tee-Object -FilePath '%UI_LATEST%'"

:success_msg
echo.
echo ============================================
echo Chintu Launched!
echo ============================================
timeout /t 5
