@echo off
setlocal
title LocalCoder - models on disk
cd /d "%~dp0"

if exist "%~dp0config.cmd" call "%~dp0config.cmd"

if not exist "venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run SETUP.bat first.
  pause
  exit /b 1
)

venv\Scripts\python.exe supervisor.py --list
echo.
pause
