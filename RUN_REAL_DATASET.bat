@echo off
setlocal
cd /d "%~dp0backend"
python -m pip install -r requirements.txt || goto :fail
python scripts\build_real_dataset.py --start-year 2016 --end-year 2025 --negatives-per-event 5 --workers 6 || goto :fail
python scripts\train_real_model.py || goto :fail
python scripts\self_test.py || goto :fail

echo.
echo REAL DATASET + REAL AI MODEL READY.
start "SIH26001 Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
cd /d "%~dp0frontend"
if not exist node_modules (
  echo Installing frontend dependencies...
  call npm install || goto :fail
)
echo Starting frontend...
call npm run dev
exit /b 0
:fail
echo.
echo SETUP FAILED. Read the error above and fix the reported network/dependency issue.
pause
exit /b 1
