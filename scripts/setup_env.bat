@echo off
setlocal
title Chintu AI - One-Click Setup

echo ========================================================
echo       Chintu AI - Environment Setup Wizard
echo ========================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from python.org and try again.
    pause
    exit /b 1
)

:: Create Virtual Environment
if not exist "venv" (
    echo [INFO] Creating virtual environment 'venv'...
    python -m venv venv
) else (
    echo [INFO] Virtual environment 'venv' already exists.
)

:: Activate Virtual Environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: Upgrade PIP
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

:: Install Dependencies
if exist "requirements.txt" (
    echo [INFO] Installing dependencies from requirements.txt...
    echo This may take a few minutes depending on your internet connection.
    pip install -r requirements.txt
) else (
    echo [WARNING] requirements.txt not found! Skipping dependency install.
)

:: Setup .env file
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Creating .env config file from template...
        copy .env.example .env
        echo [IMPORTANT] A new .env file has been created. 
        echo             Please edit it to add your API keys!
    )
)

echo.
echo ========================================================
echo       Setup Complete! 
echo ========================================================
echo.
echo To start Chintu AI, run: start_chintu.bat
echo.
pause
