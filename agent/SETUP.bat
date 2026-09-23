@echo off
setlocal
title OrthrosCode agent - Setup
cd /d "%~dp0"

echo ============================================================
echo   OrthrosCode agent setup
echo   Installs everything into %~dp0venv
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH.
  echo Install Python 3.10+ and tick "Add to PATH", then run this again.
  pause
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
) else (
  echo Virtual environment already present - reusing it.
)

REM OrthrosCode: the packages both agents use are installed once, in
REM ..\shared-venv. This venv sees them through orthros_shared.pth and layers
REM its own on top: whatever is installed here wins over the shared copy and
REM never reaches the other agent. Skipped if the Python versions differ.
set "SHARED="
if exist "..\shared-venv\Lib\site-packages" if exist "orthros_shared.pth" set "SHARED=1"
if defined SHARED copy /y "orthros_shared.pth" "venv\Lib\site-packages\" >nul
if defined SHARED echo Using the shared packages in ..\shared-venv, with this agent's own on top.

if not defined SHARED (
  echo.
  echo Upgrading pip...
  venv\Scripts\python.exe -m pip install --upgrade pip --quiet --disable-pip-version-check
)

echo.
echo Installing dependencies. This takes a few minutes the first time.
echo.
venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo Dependency install FAILED. Scroll up for the reason.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Setup complete.
echo.
echo   1. Run LIST_MODELS.bat  - see which models you have
echo   2. Edit config.cmd      - paste the model key in
echo   3. Run LAUNCH.bat       - start coding
echo ============================================================
echo.
pause
