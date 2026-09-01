@echo off
REM Run PDF Document Intelligence (Windows). Plain ASCII only - see
REM install.bat for why (chcp 65001 + non-ASCII text corrupted the batch
REM parser on some real Windows 10 machines).
cd /d "%~dp0"

if not exist ".venv" (
  echo Not installed yet - please double-click install.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

REM Open specifically in Chrome rather than whatever the OS default
REM browser happens to be - checked in the three places a real Chrome
REM install actually lands (per-machine Program Files x64/x86, or a
REM per-user install under LocalAppData with no admin rights). Falls back
REM to the OS default browser via plain "start" if none of those exist,
REM so a machine without Chrome still opens the app instead of failing.
set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if defined CHROME_EXE (
  start "" "%CHROME_EXE%" http://localhost:8000
) else (
  start "" http://localhost:8000
)
echo Starting the app at http://localhost:8000 - close this window to stop the server.
uvicorn pdf_document_intelligence.api.app:app --host 0.0.0.0 --port 8000
