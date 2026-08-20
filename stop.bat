@echo off
REM Stops the server started by run_hidden.vbs (no window to close by hand).
setlocal enabledelayedexpansion
set FOUND=

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%a >nul 2>nul
  set FOUND=1
)

if defined FOUND (
  echo [DONE] Server stopped.
) else (
  echo [INFO] No server was running on port 8000.
)
pause
