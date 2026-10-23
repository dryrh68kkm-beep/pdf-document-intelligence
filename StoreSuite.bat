@echo off
REM Store Suite - one program for PDF Document Intelligence, Expiry Dashboard and Stock Atlas.
REM First run: installs Python 3.11 (via winget) if missing, creates .venv, installs packages.
REM Plain ASCII only.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

call :findpy
if defined PY goto mkvenv

echo Python 3.11+ not found - installing Python 3.11 with winget...
where winget >nul 2>nul
if errorlevel 1 (
  echo winget is not available. Install Python 3.11+ from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^) and run this file again.
  pause
  exit /b 1
)
winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
call :findpy
if not defined PY (
  echo Python was installed, but this window cannot see it yet.
  echo Close this window and double-click StoreSuite.bat again.
  pause
  exit /b 1
)

:mkvenv
echo Using: %PY%
%PY% -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install -e ".[api,ocr]" || (pause & exit /b 1)
goto start

:run
call .venv\Scripts\activate.bat

:start
echo Starting Store Suite at http://localhost:8000  (Ctrl+C to stop)
python scripts\run_suite.py
exit /b 0

:findpy
set "PY="
for %%C in ("py -3.13" "py -3.12" "py -3.11" "python") do (
  if not defined PY (
    %%~C -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=%%~C"
  )
)
exit /b 0
