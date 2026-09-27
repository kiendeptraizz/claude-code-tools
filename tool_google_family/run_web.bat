@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Google Family Tool - DUNG DONG cua so nay (thu nho la duoc)
call venv\Scripts\activate.bat
echo ==================================================================
echo   DAY LA "DONG CO" web tool Google Family. Hay THU NHO cua so nay.
echo   Trinh duyet se tu mo tool sau vai giay ( http://127.0.0.1:8500 ).
echo   Muon tat han: dong cua so nay.
echo ==================================================================
start "" /b cmd /c "ping -n 9 127.0.0.1 >nul & start http://127.0.0.1:8500"
python -m uvicorn web:app --host 127.0.0.1 --port 8500
