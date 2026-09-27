@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Hotmail Tool - DUNG DONG cua so nay (thu nho la duoc)
call venv\Scripts\activate.bat
echo ==================================================================
echo   DAY LA "DONG CO" web tool Hotmail. Hay THU NHO cua so nay, DUNG DONG.
echo   Trinh duyet se tu mo sau vai giay ( http://127.0.0.1:8700 ).
echo ==================================================================
start "" /b cmd /c "ping -n 9 127.0.0.1 >nul & start http://127.0.0.1:8700"
python -m uvicorn web:app --host 127.0.0.1 --port 8700
