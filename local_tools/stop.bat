@echo off
title Stop Discord Bot
color 0c
cls

echo.
echo  =========================================
echo    STOPPING DISCORD BOT ^& DASHBOARD
echo  =========================================
echo.

REM Kill the launcher window and any python process with the bot title
taskkill /F /FI "WINDOWTITLE eq Discord Music Bot*" /T >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Discord Music Bot*" /T >nul 2>&1

REM Kill anything on port 8000 (the dashboard port)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1

echo [OK] Bot and Dashboard have been stopped.
echo.
pause
