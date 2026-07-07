@echo off
title Kalshi Trading Bot - LIVE
echo ============================================
echo   Kalshi Trading Bot - STARTING LIVE MODE
echo ============================================
echo.
echo DO NOT CLOSE THIS WINDOW - minimize it instead
echo To stop the bot: double-click STOP-BOT.bat
echo.
cd /d C:\Users\robgk\kalshi-bot
C:\Users\robgk\AppData\Local\Programs\Python\Python312\python.exe -m src --live-confirm
echo.
echo Bot has stopped.
pause
