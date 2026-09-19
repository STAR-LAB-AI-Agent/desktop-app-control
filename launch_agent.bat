@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0launch_agent.ps1"
if errorlevel 1 pause
