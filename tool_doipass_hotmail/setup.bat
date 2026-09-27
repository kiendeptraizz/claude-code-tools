@echo off
chcp 65001 >nul
echo === Cai dat tool doi pass Hotmail ===
python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
echo.
echo === Cai dat xong! ===
echo Buoc tiep theo:
echo   1. Dan account vao data\accounts.txt
echo   2. Chay: run_test.bat  (kiem tra token)
echo   3. Chay: run.bat       (doi pass)
pause
