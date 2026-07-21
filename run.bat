@echo off
cd /d "%~dp0"
echo ============================================
echo   KYC Verifier - starting up
echo ============================================
echo Installing / checking dependencies...
python -m pip install -q -r requirements.txt
echo.
echo Open  http://127.0.0.1:8000  in your browser.
echo Press Ctrl+C to stop.
echo.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
