@echo off
rem Finance Hub — start (runs in the background with a tray icon; a second start just opens the browser)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  call install.bat
  exit /b
)
start "" ".venv\Scripts\pythonw.exe" FinanceHub.pyw
