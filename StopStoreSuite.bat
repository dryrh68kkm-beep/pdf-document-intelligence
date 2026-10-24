@echo off
REM Stops the Store Suite server started from the Desktop shortcut. Plain ASCII only.
set "PIDFILE=%LOCALAPPDATA%\store-suite\server.pid"
if not exist "%PIDFILE%" (
  echo Store Suite is not running.
  pause
  exit /b 0
)
set /p APPPID=<"%PIDFILE%"
echo %APPPID%| findstr /R "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo PID file is invalid - not stopping anything.
  del "%PIDFILE%" >nul 2>nul
  pause
  exit /b 0
)
tasklist /FI "PID eq %APPPID%" /FI "IMAGENAME eq pythonw.exe" 2>nul | find "%APPPID%" >nul
if errorlevel 1 tasklist /FI "PID eq %APPPID%" /FI "IMAGENAME eq python.exe" 2>nul | find "%APPPID%" >nul
if errorlevel 1 (
  echo The recorded process is not Store Suite any more - not stopping anything.
  del "%PIDFILE%" >nul 2>nul
  pause
  exit /b 0
)
taskkill /PID %APPPID% /T /F
del "%PIDFILE%" >nul 2>nul
echo Store Suite stopped.
pause
