@echo off
title GROWISE INVEST - Build Check
cd /d "%~dp0client"
echo Checking React/Vite build...
npm run build
if errorlevel 1 (
  echo.
  echo BUILD FAILED. Read the error above.
  pause
  exit /b 1
)
echo.
echo BUILD PASSED.
pause
