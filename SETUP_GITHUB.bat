@echo off
setlocal
title Akaza GitHub Setup
cd /d "%~dp0"

echo.
echo  =========================================
echo    PREPARING YOUR BOT FOR GITHUB
echo  =========================================
echo.

git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed! 
    echo Please download it from: https://git-scm.com/
    pause
    exit
)

echo [1/3] Initializing local repository...
git init

echo [2/3] Adding files (following .gitignore)...
git add .
git commit -m "Deployment ready version"
git branch -M main

echo.
echo [3/3] SETUP COMPLETE!
echo.
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo IMPORTANT: Make sure your BOT_TOKEN is NOT 
echo in config.py. It should be in Render's
echo Environment Variables!
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo.
echo WHAT TO DO NEXT:
echo 1. Go to github.com and create a NEW repository.
echo 2. Copy the "Remote URL" they give you.
echo 3. Paste these two commands:
echo    "git remote add origin YOUR_URL_HERE"
echo    "git push -u origin main"
echo.
pause
