@echo off
REM Install PDF Document Intelligence (Windows).
REM Plain ASCII only, on purpose: this batch file previously used "chcp
REM 65001" plus Thai text to make its messages readable, but on several
REM real Windows 10 machines (build 17763 confirmed) that combination
REM corrupts the batch parser itself - individual words from later lines
REM (e.g. the "-m" in "python -m venv") got treated as their own stray
REM commands, producing a wall of "'X' is not recognized" errors. Staying
REM in plain ASCII sidesteps the codepage bug entirely instead of working
REM around it.
cd /d "%~dp0"
set "APPDIR=%CD%"

echo == 1/3 Checking Python ==
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo Please install it from https://www.python.org/downloads/
  echo During setup, check the box "Add python.exe to PATH".
  pause
  exit /b 1
)
REM pyproject.toml requires-python = ">=3.11" - a python.exe that merely
REM exists but is too old used to fail deep inside "pip install -e ." with
REM a confusing dependency-resolution error instead of a clear message here.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo [ERROR] Python found but it is too old.
  echo This app needs Python 3.11 or newer.
  echo Please install a newer version from https://www.python.org/downloads/
  pause
  exit /b 1
)
echo [OK] Python found.

where tesseract >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Tesseract OCR not found.
  echo Please install it from https://github.com/UB-Mannheim/tesseract/wiki
  echo During setup, select the Thai language pack.
  echo Then run this file again.
  pause
  exit /b 1
)
echo [OK] Tesseract found.

echo == 2/3 Installing Python dependencies ==
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -e ".[ocr,api,dev]"
if errorlevel 1 (
  echo [ERROR] pip install failed - see the messages above for details.
  pause
  exit /b 1
)

echo == 3/3 Creating Desktop shortcut ==
if not exist "assets\app_icon.ico.b64" (
  echo [WARN] Desktop icon source is missing. Shortcut will not be created.
  goto install_done
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$b=[IO.File]::ReadAllText((Join-Path $env:APPDIR 'assets\app_icon.ico.b64')); [IO.File]::WriteAllBytes((Join-Path $env:APPDIR 'assets\app_icon.ico'),[Convert]::FromBase64String($b))"
if errorlevel 1 (
  echo [WARN] Could not prepare the Desktop icon. Shortcut will not be created.
  goto install_done
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $s=$w.CreateShortcut((Join-Path $desktop 'PDF Document Intelligence.lnk')); $s.TargetPath=(Join-Path $env:WINDIR 'System32\wscript.exe'); $s.Arguments='"' + (Join-Path $env:APPDIR 'run_hidden.vbs') + '"'; $s.WorkingDirectory=$env:APPDIR; $s.IconLocation=(Join-Path $env:APPDIR 'assets\app_icon.ico') + ',0'; $s.Description='PDF Document Intelligence'; $s.Save()"
if errorlevel 1 (
  echo [WARN] Install finished, but the Desktop shortcut could not be created.
) else (
  echo [OK] Desktop shortcut created.
)

:install_done
echo.
echo [DONE] Install complete!
echo Use the "PDF Document Intelligence" shortcut on your Desktop to start the app.
pause
