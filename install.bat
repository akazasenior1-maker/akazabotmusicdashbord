@echo off
title Music Bot Installer
color 0e
cls

set BOT_DIR=%~dp0
cd /d "%BOT_DIR%"

echo.
echo  =========================================
echo    INSTALLING DEPENDENCIES
echo  =========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Please install it from https://python.org
    pause
    exit /b
)

REM Create venv if missing
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

echo [INFO] Installing required libraries...
.\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo  =========================================
echo    INSTALLATION COMPLETE!
echo  =========================================
echo.
echo  1. Add your Client Secret to config.py
echo  2. Add http://localhost:8000/auth/callback to Discord Portal
echo  3. Run start.bat to begin.
echo.
pause
