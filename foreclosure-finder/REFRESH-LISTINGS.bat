@echo off
title Foreclosure Finder - refreshing listings
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
%PY% -m pip install --quiet fastapi uvicorn httpx
echo Pulling every HUD, Fannie Mae HomePath and Freddie Mac HomeSteps listing.
echo This takes about an hour. You can keep using the site meanwhile.
%PY% -m app.scrape --source hud
%PY% -m app.scrape --source homepath
%PY% -m app.scrape --source homesteps
echo Done.
pause
