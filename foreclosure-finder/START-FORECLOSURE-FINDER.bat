@echo off
title Foreclosure Finder
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python was not found. Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
echo Installing requirements (first run takes a minute)...
%PY% -m pip install --quiet fastapi uvicorn httpx
echo.
set /p RENTCAST_API_KEY=Paste your RentCast API key for sold comps (or just press Enter to skip): 
echo.
echo Opening http://localhost:8000 ...
start "" http://localhost:8000
echo Keep this window open while you use the site. Close it to stop.
%PY% -m uvicorn app.server:app --port 8000
pause
