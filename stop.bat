@echo off
REM Stop only the PDF Document Intelligence server that owns server.pid.
REM Never kill an unrelated process just because it happens to use port 8000.
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv" (
  echo [INFO] PDF Document Intelligence is not installed here.
  pause
  exit /b 0
)

call .venv\Scripts\activate.bat
set "PIDFILE="
for /f "delims=" %%p in ('python -c "from pdf_document_intelligence.db.paths import get_data_dir; print(get_data_dir() / 'server.pid')"') do set "PIDFILE=%%p"

if not defined PIDFILE (
  echo [INFO] Could not resolve the app PID file.
  pause
  exit /b 0
)
if not exist "%PIDFILE%" (
  echo [INFO] No PDF Document Intelligence server is running.
  pause
  exit /b 0
)

set /p APPPID=<"%PIDFILE%"
echo %APPPID%| findstr /R "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo [WARN] Stale or invalid PID file. Nothing was stopped.
  del /q "%PIDFILE%" >nul 2>nul
  pause
  exit /b 0
)

REM Verify that the recorded PID is really this app's launcher.
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%APPPID%' -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -like '*scripts\run_server.py*'){exit 0}else{exit 1}"
if errorlevel 1 (
  echo [WARN] PID %APPPID% does not belong to this app. Nothing was stopped.
  del /q "%PIDFILE%" >nul 2>nul
  pause
  exit /b 0
)

REM Also require the same PID to own the listener on port 8000.
set "OWNSPORT="
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
  if "%%a"=="%APPPID%" set "OWNSPORT=1"
)
if not defined OWNSPORT (
  echo [WARN] App PID is not listening on port 8000. Nothing was stopped.
  del /q "%PIDFILE%" >nul 2>nul
  pause
  exit /b 0
)

taskkill /F /T /PID %APPPID% >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Could not stop the app process.
) else (
  del /q "%PIDFILE%" >nul 2>nul
  echo [DONE] PDF Document Intelligence server stopped.
)
pause
