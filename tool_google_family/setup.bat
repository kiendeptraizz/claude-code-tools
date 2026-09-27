@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Cai dat tool check Google Family ===
python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo === Xong! (KHONG can tai Chromium - dung browser cua GPM) ===
echo Buoc tiep: mo GPM Login + bat API, roi chay run_gui.bat
pause
