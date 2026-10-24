@echo off
REM Same as StoreSuite.bat but with a visible console (to see errors live). Plain ASCII only.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run StoreSuite.bat first to install.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python scripts\run_suite.py
pause
