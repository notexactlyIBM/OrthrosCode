@echo off
setlocal
title OrthrosCode - setup
cd /d "%~dp0"

REM Builds shared-venv and the two agents, OrthrosCode A and B, from agent\.
REM Safe to run again: it only creates what is missing.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python 3.10 or newer was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

%PY% orthros_setup.py %*
echo.
pause
