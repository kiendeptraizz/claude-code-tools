@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChatGPT Tool - DUNG DONG cua so nay (thu nho la duoc)
call venv\Scripts\activate.bat
echo ==================================================================
echo   DAY LA "DONG CO" web tool. Hay THU NHO cua so nay, DUNG DONG.
echo   Trinh duyet se tu mo tool sau vai giay ( http://127.0.0.1:8600 ).
echo   Muon tat han: dong cua so nay.
echo ==================================================================
start "" /b cmd /c "ping -n 9 127.0.0.1 >nul & start http://127.0.0.1:8600"
python -m uvicorn web:app --host 127.0.0.1 --port 8600
