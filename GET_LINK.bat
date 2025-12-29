@echo off
setlocal
title Get Public Dashboard Link (Zero-Install)
cd /d "%~dp0"

echo.
echo  =========================================
echo    GENERATING PUBLIC DASHBOARD LINK
echo  =========================================
echo.
echo [INFO] Make sure your dashboard is running (start.bat or Background Service).
echo [INFO] Connecting to secure tunnel...
echo [INFO] NOTE: Copy the link that starts with https:// below.
echo.

REM Using localhost.run via SSH (Zero install needed!)
ssh -R 80:localhost:8000 nokey@localhost.run
