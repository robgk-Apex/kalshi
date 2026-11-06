@echo off
title Foreclosure Finder
cd /d "%~dp0"
echo Installing / updating requirements (first run takes a minute)...
python -m pip install --quiet fastapi uvicorn httpx
echo.
echo Opening http://localhost:8000 ...
start "" http://localhost:8000
echo Keep this window open while you use the site. Close it to stop.
python -m uvicorn app.server:app --port 8000
pause
