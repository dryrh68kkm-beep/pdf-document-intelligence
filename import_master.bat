@echo off
REM Import the store master catalog CSV into the app's private data folder.
REM Plain ASCII only - see install.bat for why (chcp 65001 + non-ASCII text
REM corrupted the batch parser on some real Windows 10 machines).
cd /d "%~dp0"

if not exist ".venv" (
  echo Not installed yet - please double-click install.bat first.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Usage: drag and drop your master catalog CSV file onto this file,
  echo        or run:  import_master.bat "C:\path\to\file.csv"
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python -c "import sys; from pathlib import Path; from pdf_document_intelligence.catalog.snapshot import import_catalog_snapshot; p = import_catalog_snapshot(Path(sys.argv[1]), overwrite=True); print('Imported master catalog to:', p)" "%~1"
if errorlevel 1 (
  echo [ERROR] Import failed - see the message above for details.
  pause
  exit /b 1
)

echo.
echo [DONE] Master catalog imported. Restart the app (run.bat) to use it.
pause
