@echo off
setlocal
title LocalCoder - stop everything
cd /d "%~dp0"

REM Normally you never need this: closing the LocalCoder window cleans up by
REM itself. Use this if something was killed the hard way (Task Manager, a
REM crash) and the model is still sitting in your graphics card.

if not exist "venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run SETUP.bat first.
  pause
  exit /b 1
)

echo Unloading the model and stopping the LM Studio server...
echo.
venv\Scripts\python.exe supervisor.py --stop
echo.
pause
