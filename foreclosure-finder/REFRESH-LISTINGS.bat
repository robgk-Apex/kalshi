@echo off
title Foreclosure Finder - refreshing listings
cd /d "%~dp0"
python -m pip install --quiet fastapi uvicorn httpx
echo Pulling every HUD, Fannie Mae HomePath and Freddie Mac HomeSteps listing.
echo This takes about an hour. You can keep using the site meanwhile.
python -m app.scrape --source hud
python -m app.scrape --source homepath
python -m app.scrape --source homesteps
echo Done.
pause
