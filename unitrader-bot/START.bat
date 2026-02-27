@echo off
title Unitrader Launcher
echo.
echo  ============================================================
echo   UNITRADER - Starting Everything...
echo  ============================================================
echo.

:: Start the main startup script
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1"
