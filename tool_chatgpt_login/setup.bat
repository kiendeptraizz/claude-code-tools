@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Cai dat tool login ChatGPT hang loat ===
python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install playwright requests pyotp
echo.
echo === Xong! (KHONG can tai Chromium - dung browser cua GPM) ===
echo Buoc tiep: mo GPM Login + bat API; dan acc vao data\accounts.txt; chay run.bat
pause
