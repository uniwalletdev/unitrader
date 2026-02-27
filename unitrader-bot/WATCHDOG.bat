@echo off
title Unitrader Watchdog - Auto-Restart Monitor
echo.
echo  ============================================================
echo   UNITRADER WATCHDOG - Auto-Restart Monitor
echo   Keep this window open. It will restart services if they
echo   crash. Press Ctrl+C to stop.
echo  ============================================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0watchdog.ps1"
pause
