@echo off
setlocal enabledelayedexpansion
title Discord Music Bot + Dashboard
color 0b
cls

echo.
echo  =========================================
echo    DISCORD MUSIC BOT + DASHBOARD
echo  =========================================
echo.

REM Kill any process on port 8000 (the dashboard port) before starting
echo [INFO] Ensuring Port 8000 is clear...
netstat -ano | findstr :8000 | findstr LISTENING > %temp%\pid.txt
if %errorlevel% equ 0 (
    for /f "tokens=5" %%a in (%temp%\pid.txt) do (
        echo [INFO] Found process %%a on port 8000. Killing it...
        taskkill /f /pid %%a >nul 2>&1
    )
)

echo.
echo  -----------------------------------------
echo   BOT IS STARTING...
echo   DASHBOARD: http://localhost:8000
echo  -----------------------------------------
echo.

REM Verify virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run install.bat first.
    pause
    exit /b
)

.\venv\Scripts\python.exe manager.py 
if errorlevel 1 (
    echo.
    echo [ERROR] Bot crashed or stopped.
    echo Please make sure your config.py is correct.
    echo.
    pause
)
