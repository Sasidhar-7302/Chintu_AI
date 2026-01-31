@echo off
setlocal enabledelayedexpansion

title Chintu AI - Professional Suite
color 0B

echo.
echo  ##########################################################################
echo  #                                                                        #
echo  #                       CHINTU AI ASSISTANT v5.1                         #
echo  #                   The Ultimate Desktop AI Intelligence                 #
echo  #                                                                        #
echo  ##########################################################################
echo.

cd /d "%~dp0"

echo [SYSTEM] Cleaning up stale backend processes...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8765') do taskkill /F /PID %%a >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Chintu Backend" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Chintu UI Dev" >nul 2>&1

echo [SYSTEM] Verifying environment...
if exist venv\Scripts\activate.bat goto :ACTIVATE
echo [SYSTEM] Creating new environment...
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
goto :START

:ACTIVATE
echo [OK] Environment found.
call venv\Scripts\activate.bat

:START
echo [BACKEND] Starting Chintu Core...
start "Chintu Backend" /min venv\Scripts\python.exe main.py
ping -n 3 127.0.0.1 >nul
echo [OK] Backend synchronized.

echo [INTERFACE] Initializing UI...
set UI_PATH=chintu_ui\build\windows\x64\runner\Release\chintu_ui.exe

if exist "%UI_PATH%" goto :PROD_UI
echo [WARNING] Production build missing.
echo [SYSTEM] Starting dev instance...
cd chintu_ui
start "Chintu UI Dev" cmd /c "flutter run -d windows"
cd ..
goto :EXIT

:PROD_UI
echo [OK] Production build found.
start "" "%UI_PATH%"

:EXIT
echo  --------------------------------------------------------------------------
echo   CHINTU IS NOW ONLINE
echo  --------------------------------------------------------------------------
ping -n 6 127.0.0.1 >nul
exit /b 0
