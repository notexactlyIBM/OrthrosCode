@echo off
setlocal
title LocalCoder - self test
cd /d "%~dp0"

if not exist "%~dp0config.cmd" (
  echo config.cmd is missing.
  pause
  exit /b 1
)
call "%~dp0config.cmd"

if not exist "venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run SETUP.bat first.
  pause
  exit /b 1
)

echo Testing the whole chain without opening the chat box.
echo.
venv\Scripts\python.exe supervisor.py --check
echo.
pause
