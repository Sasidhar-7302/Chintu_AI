@echo off
echo ============================================
echo    Chintu Personal AI Assistant
echo ============================================
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo Error: Virtual environment not found!
    echo Run: python -m venv venv
    pause
    exit /b 1
)

REM Check System Health and Dependencies
echo Running Pre-flight Checks...
venv\Scripts\python tools\check_deps.py
if %errorlevel% equ 3 (
    echo [INFO] FFmpeg not found
    echo 🎬 FFmpeg missing. Attempting Automatic Installation...
    venv\Scripts\python tools\install_ffmpeg.py
    if %errorlevel% neq 0 (
        echo [ERROR] FFmpeg install failed.
        pause
        exit /b 1
    )
    REM Re-run check
    venv\Scripts\python tools\check_deps.py
)
if %errorlevel% equ 2 (
    echo [ERROR] System Check Failed
    echo 🛑 STOPPING: Critical system requirements missing.
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
    REM Re-run check to verify system health after pip install
    venv\Scripts\python tools\check_deps.py
)

echo Dependencies satisfied.

REM Start Python backend FIRST in background
echo Starting Chintu Backend...
start "Chintu Backend" cmd /k "cd /d %~dp0 && venv\Scripts\python -u main.py"

REM Wait for backend WebSocket to be ready (check port 8765)
echo Waiting for backend to initialize...
set /a count=0
:waitloop
timeout /t 2 /nobreak >nul
set /a count+=1
netstat -an | find "8765" | find "LISTENING" >nul
if %errorlevel% equ 0 (
    echo Backend ready on port 8765!
    goto :startui
)
if %count% geq 30 (
    echo WARNING: Backend not ready after 60 seconds, starting UI anyway...
    goto :startui
)
echo    Still waiting... (%count%/30)
goto :waitloop

:startui
REM Now start Flutter UI (backend should be ready)
echo Launching Flutter UI...
start "Chintu UI" cmd /k "cd /d %~dp0\chintu_ui && flutter run -d windows"

echo.
echo ============================================
echo Both services started!
echo - Python backend: ws://127.0.0.1:8765
echo - Flutter UI: Opening...
echo ============================================
echo.
echo Press any key to close this launcher...
pause >nul
