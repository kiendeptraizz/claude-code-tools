@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tool MMO Hub - DUNG DONG cua so nay (thu nho la duoc)
call venv\Scripts\activate.bat
echo ==================================================================
echo   HUB TONG HOP TOOL MMO. Hay THU NHO cua so nay, DUNG DONG.
echo   Trinh duyet se tu mo sau vai giay ( http://127.0.0.1:8000 ).
echo   Chon tool ben trai -> tool tu khoi dong + hien trong khung.
echo ==================================================================
start "" /b cmd /c "ping -n 6 127.0.0.1 >nul & start http://127.0.0.1:8000"
python -m uvicorn hub:app --host 127.0.0.1 --port 8000
