@echo off
title LocalCoder dashboard - keep this window open
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run SETUP.bat first.
  pause
  exit /b 1
)
venv\Scripts\python.exe gui.py %*
