@echo off
setlocal
title Unregister Akaza Dashboard Service

echo.
echo  =========================================
echo    REMOVING BACKGROUND SERVICE
echo  =========================================
echo.

schtasks /delete /tn "AkazaMusicDashboard" /f

if %errorlevel% equ 0 (
    echo.
    echo [OK] Background service removed.
) else (
    echo.
    echo [INFO] Service was not found or already removed.
)

echo.
pause
