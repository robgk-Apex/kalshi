@echo off
echo ============================================
echo   Kalshi Bot Status
echo ============================================
echo.

REM Check if running
tasklist /fi "windowtitle eq Kalshi Bot" 2>nul | find "cmd" >nul
if %errorlevel%==0 (
    echo Status: RUNNING
) else (
    tasklist | find "python.exe" >nul
    if %errorlevel%==0 (
        echo Status: RUNNING (python detected)
    ) else (
        echo Status: STOPPED
    )
)
echo.

REM Show last 20 lines of log
echo --- Last 20 log lines ---
if exist logs\bot.log (
    powershell -command "Get-Content logs\bot.log -Tail 20"
) else (
    echo No log file found.
)
echo.

REM Show paper trade summary
if exist logs\paper_trades.json (
    echo --- Paper Trades ---
    powershell -command "$j = Get-Content logs\paper_trades.json | ConvertFrom-Json; Write-Host ('Balance: $' + $j.balance); Write-Host ('Trades: ' + $j.trade_count); Write-Host ('Open positions: ' + ($j.positions.PSObject.Properties.Name.Count)); Write-Host ('Closed trades: ' + $j.closed_trades.Count)"
) else (
    echo No paper trades yet.
)
echo.
pause
