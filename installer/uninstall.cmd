@echo off
setlocal
title Uninstall Claude Code Manager
rem Double-click to uninstall. Keeps or removes data per user choice in uninstall.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
echo Uninstall finished. You may close this window.
pause
