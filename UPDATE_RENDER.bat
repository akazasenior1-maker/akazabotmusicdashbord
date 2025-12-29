@echo off
setlocal
title Akaza Senior Push
cd /d "%~dp0"

echo.
echo  =========================================
echo    PUSHING SENIOR UPDATES TO GITHUB
echo  =========================================
echo.

git add .
git commit -m "Akaza Senior Optimization: Stable, High Quality, Fast Sync"
git branch -M main

echo [OK] Changes committed locally.
echo.
echo Pushing to GitHub...
git push origin main

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Push failed. 
    echo Make sure you have added the remote:
    echo git remote add origin YOUR_REPOSITORY_URL
    pause
    exit
)

echo.
echo  =========================================
echo    UPDATE COMPLETE!
echo  =========================================
echo  Render should now start building automatically.
echo.
pause
