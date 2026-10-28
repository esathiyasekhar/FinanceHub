@echo off
rem Optional: turn this setup folder into one FinanceHub_<version>_Setup.exe (needs Inno Setup 6 installed).
cd /d "%~dp0"
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 is not installed. Get it free from https://jrsoftware.org/isinfo.php and run this again.
  echo You do not need it to install Finance Hub - just double-click Setup.cmd.
  pause
  exit /b 1
)
for %%f in (FinanceHub_*.zip) do set "ZIP=%%~nf"
set "FH_VERSION=%ZIP:FinanceHub_=%"
"%ISCC%" FinanceHub_Setup.iss && echo. && echo Built FinanceHub_%FH_VERSION%_Setup.exe
pause
