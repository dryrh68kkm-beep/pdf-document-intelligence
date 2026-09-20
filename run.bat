@echo off
REM Run PDF Document Intelligence (Windows). Plain ASCII only.
cd /d "%~dp0"

if not exist ".venv" (
  echo Not installed yet - please double-click install.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

REM scripts\run_server.py owns the server PID, waits for /api/health, and
REM opens Chrome (or the default browser) only after the app is ready.
echo Starting PDF Document Intelligence at http://localhost:8000
python scripts\run_server.py
