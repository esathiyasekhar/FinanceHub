@echo off
rem Finance Hub setup — double-click to install or upgrade.   Setup.cmd /uninstall  removes the program (your data is kept).
setlocal
cd /d "%~dp0"
set "ARGS="
if /i "%~1"=="/uninstall" set "ARGS=--uninstall"
if /i "%~1"=="/silent" set "ARGS=--silent --desktop --start"
set "PYW="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PYW=pyw -3"
if not defined PYW (where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PYW=pythonw")
if not defined PYW goto :nopython
start "" /wait %PYW% "%~dp0setup.pyw" %ARGS%
exit /b 0

:nopython
echo.
echo  Finance Hub needs Python 3.10 or newer (free, from python.org).
echo  The download page opens now. While installing Python, tick "Add python.exe to PATH",
echo  then double-click Setup.cmd again.
echo.
start "" https://www.python.org/downloads/windows/
pause
exit /b 1
