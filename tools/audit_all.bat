@echo off
echo ============================================
echo      Chintu System Self-Audit Tool
echo ============================================
echo.

echo 1. Checking System Dependencies...
echo --------------------------------------------
..\venv\Scripts\python check_deps.py
echo.

echo 2. Auditing Feature Capabilities...
echo --------------------------------------------
..\venv\Scripts\python audit_features.py
echo.

echo 3. Auditing Code Quality (Blocking Calls & safety)...
echo --------------------------------------------
..\venv\Scripts\python audit_code.py
echo.

echo ============================================
echo Audit Complete.
echo ============================================
pause
