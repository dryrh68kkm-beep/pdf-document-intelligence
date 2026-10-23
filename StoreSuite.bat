@echo off
REM Store Suite - one program for PDF Document Intelligence, Expiry Dashboard and Stock Atlas.
REM First run: creates .venv and installs. Plain ASCII only.
cd /d "%~dp0"
if not exist ".venv" (
  echo First run - installing...
  python -m venv .venv || (echo Python 3.11+ is required & pause & exit /b 1)
  call .venv\Scripts\activate.bat
  pip install -e ".[api,ocr]" || (pause & exit /b 1)
) else (
  call .venv\Scripts\activate.bat
)
echo Starting Store Suite at http://localhost:8000  (Ctrl+C to stop)
python scripts\run_suite.py
