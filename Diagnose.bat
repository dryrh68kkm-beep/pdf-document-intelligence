@echo off
REM Collects what is needed to find out why Store Suite will not start.
REM Writes StoreSuite-report.txt on the Desktop and opens it. Plain ASCII only.
cd /d "%~dp0"
set "OUT=%USERPROFILE%\Desktop\StoreSuite-report.txt"
echo Collecting information, please wait...
(
  echo ===== Store Suite report =====
  date /t & time /t
  echo Folder: %CD%
  echo.
  echo --- Python on PATH ---
  where python 2>&1
  python --version 2>&1
  where py 2>&1
  py -0 2>&1
  echo.
  echo --- .venv ---
  if exist ".venv\Scripts\python.exe" ( .venv\Scripts\python.exe --version 2>&1 ) else ( echo NO .venv folder - run StoreSuite.bat first )
  echo.
  echo --- can the program be imported? ---
  if exist ".venv\Scripts\python.exe" .venv\Scripts\python.exe -X faulthandler -c "import store_suite.app; print('import OK')" 2>&1 && echo result: finished normally || echo result: CRASHED or failed
  echo.
  echo --- installed packages ---
  if exist ".venv\Scripts\python.exe" .venv\Scripts\python.exe -m pip list --disable-pip-version-check 2>&1
  echo.
  echo --- ports 8000 / 8100 ---
  netstat -ano | findstr ":8000 :8100"
  echo.
  echo --- last-run.log ---
  if exist "%LOCALAPPDATA%\store-suite\last-run.log" ( type "%LOCALAPPDATA%\store-suite\last-run.log" ) else ( echo no log file )
) > "%OUT%" 2>&1
echo Done. Send the file StoreSuite-report.txt (on your Desktop) to Claude.
start notepad "%OUT%"
pause
