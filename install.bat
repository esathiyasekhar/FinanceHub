@echo off
rem Finance Hub — install or repair (safe to run again: your data is never touched)
setlocal
cd /d "%~dp0"
title Finance Hub setup
echo.
echo  Finance Hub setup
echo  -----------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || goto :nopython
if not exist ".venv\Scripts\python.exe" (
  echo  Creating the Hub's own Python environment ^(.venv^) ...
  %PY% -m venv .venv || goto :fail
)
echo  Installing / updating the packages the Hub needs (this can take a few minutes the first time) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q --disable-pip-version-check || goto :fail
".venv\Scripts\python.exe" -m pip freeze --disable-pip-version-check > requirements.lock
echo  Creating the Finance Hub shortcuts (Desktop and Start menu) ...
".venv\Scripts\python.exe" tools\shortcuts.py
echo.
echo  Done. Finance Hub starts now and keeps running in the background (look for its icon near the clock).
start "" ".venv\Scripts\pythonw.exe" FinanceHub.pyw
timeout /t 4 /nobreak >nul
exit /b 0

:nopython
echo  Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/
echo  (tick "Add python.exe to PATH"), then run install.bat again.
pause
exit /b 1

:fail
echo.
echo  Setup did not finish - see the messages above (an internet connection is needed the first time).
pause
exit /b 1
