@echo off
REM Store Suite - one program for PDF Document Intelligence, Expiry Dashboard and Stock Atlas.
REM First run: installs Python 3.11 (via winget) if missing, creates .venv, installs packages.
REM Plain ASCII only.
cd /d "%~dp0"

echo %~dp0 | findstr /i /c:".zip\\" /c:"\\Temp\\" >nul
if not errorlevel 1 (
  echo This folder looks like it is still inside the zip file / a temp folder.
  echo Right-click StoreSuite.zip, choose Extract All, move the extracted
  echo StoreSuite folder somewhere permanent ^(e.g. C:\StoreSuite^), then run it from there.
  pause
  exit /b 1
)

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
python -m pip install -q --upgrade pip
python -m pip install --retries 10 --timeout 60 --disable-pip-version-check -e ".[api,ocr]" || (pause & exit /b 1)
goto start

:run
call .venv\Scripts\activate.bat

:start
if not exist ".shortcut_done" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\make_shortcut.ps1" && echo done> ".shortcut_done"
)
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
