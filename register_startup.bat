@echo off
setlocal
cd /d "%~dp0"
title Register Akaza Dashboard Service

echo.
echo  =========================================
11: echo    REGISTERING BACKGROUND SERVICE
echo  =========================================
echo.

REM Create task to run on logon for the current user
schtasks /create /tn "AkazaMusicDashboard" /tr "wscript.exe \"%~dp0silent_launcher.vbs\"" /sc onlogon /f

if %errorlevel% equ 0 (
    echo.
    echo [OK] Dashboard registered! It will now start automatically when you log in.
    echo [INFO] You can find it in "Task Scheduler" under "AkazaMusicDashboard".
) else (
    echo.
    echo [ERROR] Failed to register task. Please run this script as Administrator.
)

echo.
pause
