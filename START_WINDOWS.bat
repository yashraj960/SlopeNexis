@echo off
setlocal
cd /d "%~dp0backend"
if not exist venv\Scripts\python.exe (
  echo Using system Python. Recommended: Python 3.12 or newer with supported wheels.
)
echo [1/3] Installing backend dependencies...
python -m pip install -r requirements.txt || goto :fail
echo [2/3] Checking backend files...
python scripts\verify_project.py || goto :fail
echo [3/3] Starting FastAPI on port 8000...
start "SIH26001 Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
timeout /t 3 >nul
cd /d "%~dp0frontend"
if not exist node_modules (
  echo Installing frontend dependencies...
  call npm install || goto :fail
)
call npm run dev
exit /b 0
:fail
echo.
echo STARTUP FAILED. Read the error above.
pause
