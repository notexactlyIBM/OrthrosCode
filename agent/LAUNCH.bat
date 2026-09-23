@echo off
setlocal enabledelayedexpansion
title RalphCoder - keep this window open
cd /d "%~dp0"

if not exist "%~dp0config.cmd" (
  echo config.cmd is missing.
  pause
  exit /b 1
)
call "%~dp0config.cmd"

REM Arguments in any order:
REM   a folder   - work there instead of the one in config.cmd.
REM                Drag and drop a folder onto this file to do that.
REM   -something - passed straight through and SKIPS the menu, so
REM                SELFTEST.bat and anything scripted still works:
REM                  --check    test the chain, open nothing
REM                  --once     one item off the task list, then stop
REM                  --loop --minutes 30
REM  Branches are labels, not nested if/else blocks, because a switch that
REM  takes a value (--minutes 45) needs the number forwarded too, and the
REM  bare "45" is neither a switch nor a folder.
set "PASS="
set "WANTVAL="
:parse
if "%~1"=="" goto parsed
set "ARG=%~1"
if "!ARG:~0,1!"=="-" goto argswitch
if defined WANTVAL goto argvalue
if exist "!ARG!\" goto argfolder
echo Ignoring "!ARG!" - that is not a folder.
echo.
goto argnext

:argswitch
set "PASS=!PASS! !ARG!"
set "WANTVAL="
if /i "!ARG!"=="--minutes" set "WANTVAL=1"
goto argnext

:argvalue
set "PASS=!PASS! !ARG!"
set "WANTVAL="
goto argnext

:argfolder
set "LC_WORKSPACE=!ARG!"
echo Working folder for this session: !ARG!
echo.

:argnext
shift
goto parse
:parsed

if not exist "venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run SETUP.bat first.
  pause
  exit /b 1
)

if "%LC_RALPH_MINUTES%"=="" set "LC_RALPH_MINUTES=30"

REM Something was passed on the command line, so the choice is already made.
if not "%PASS%"=="" goto run

echo ==============================================================
echo   LocalCoder
echo ==============================================================
echo.
echo   Folder: %LC_WORKSPACE%
echo.
echo   [1] Chat box            - you type, it answers
echo   [2] One item, then stop - takes the top of your task list
echo   [3] Work the list       - on its own for %LC_RALPH_MINUTES% minutes
echo   [4] Work the list for how long?
echo   [5] Dashboard            - the same, with a window to watch it in
echo.

REM  Each branch is its own label on purpose.  A `set /p` nested inside an
REM  if/else block makes cmd give up with "The syntax of the command is
REM  incorrect", so option 4 has to be reached by jumping, not nesting.
set "PICK="
set /p "PICK=Which one? [1] "
if "%PICK%"=="" set "PICK=1"

if "%PICK%"=="1" goto chat
if "%PICK%"=="2" goto once
if "%PICK%"=="3" goto listrun
if "%PICK%"=="4" goto ask
if "%PICK%"=="5" goto gui
echo.
echo That was not one of the options. Opening the chat box.

:gui
venv\Scripts\python.exe gui.py
exit /b 0

:chat
set "PASS="
goto run

:once
set "PASS= --once"
goto run

:listrun
set "PASS= --loop --minutes %LC_RALPH_MINUTES%"
goto run

:ask
set "MINS="
set /p "MINS=How many minutes? [%LC_RALPH_MINUTES%] "
if "%MINS%"=="" set "MINS=%LC_RALPH_MINUTES%"
set "PASS= --loop --minutes %MINS%"

:run
echo.
venv\Scripts\python.exe supervisor.py%PASS%
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" echo LocalCoder exited with code %RC% - see the message above.
echo.
pause
