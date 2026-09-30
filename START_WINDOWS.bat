@echo off
setlocal
set "ROOT=%~dp0"
title GROWISE INVEST - One Stop Technical Research

echo.
echo ==========================================================
echo   GROWISE INVEST - ONE STOP TECHNICAL RESEARCH
echo   Search ticker -> complete technical research -> reports
echo ==========================================================
echo.

where node >nul 2>&1 || (echo ERROR: Node.js not found. Install Node.js LTS and try again.&pause&exit /b 1)

REM Stop only the processes occupying the Growise ports.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=5000,5173; foreach($p in $ports){$c=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue; if($c){$c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue}}}"

echo Installing/checking backend packages...
start "GROWISE INVEST - SERVER" cmd /k "cd /d "%ROOT%server" && npm install --no-audit --no-fund && npm start"

timeout /t 3 /nobreak >nul

echo Installing/checking frontend packages...
start "GROWISE INVEST - CLIENT" cmd /k "cd /d "%ROOT%client" && npm install --no-audit --no-fund && npm run dev"

timeout /t 2 /nobreak >nul

echo.
echo Backend : http://localhost:5000
 echo Frontend: http://localhost:5173
 echo.
echo Open http://localhost:5173 and search TCS, RELIANCE, INFY, etc.
echo Do not enter module 77. The ticker search automatically runs the complete pipeline.
echo.
pause
