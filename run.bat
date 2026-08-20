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
start "" http://localhost:8000
echo Starting the app at http://localhost:8000 - close this window to stop the server.
uvicorn pdf_document_intelligence.api.app:app --host 0.0.0.0 --port 8000
