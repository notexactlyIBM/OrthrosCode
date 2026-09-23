@echo off
setlocal
title Orthros - keep this window open
cd /d "%~dp0"

REM Orthros needs only the standard library, so any Python 3.8+ will do. The
REM system one first: the agents rewrite their own folders, venvs included,
REM and the orchestrator should not depend on anything they can break.
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY if exist "OrthrosCode A\venv\Scripts\python.exe" set "PY="OrthrosCode A\venv\Scripts\python.exe""
if not defined PY if exist "OrthrosCode B\venv\Scripts\python.exe" set "PY="OrthrosCode B\venv\Scripts\python.exe""
if not defined PY (
  echo Python was not found. Install Python 3 and tick "Add to PATH".
  pause
  exit /b 1
)

%PY% orthros.py %*
if errorlevel 1 pause
