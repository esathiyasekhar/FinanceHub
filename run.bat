@echo off
cd /d "%~dp0"
echo Starting Finance Hub 1.5 ...
echo.
pip install -r requirements.txt -q
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:5000"
python app.py
pause
