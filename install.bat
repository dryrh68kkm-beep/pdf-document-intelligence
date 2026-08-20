@echo off
REM Install PDF Document Intelligence (Windows)
REM Switch the console to UTF-8 so Thai text renders correctly instead of
REM garbled boxes - the file itself is saved UTF-8, but cmd.exe defaults
REM to a legacy codepage unless told otherwise.
chcp 65001 >nul
cd /d "%~dp0"

echo == 1/2 Checking Python / ตรวจสอบ Python ==
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found / ไม่พบ Python
  echo Please install it from https://www.python.org/downloads/
  echo   During setup, check "Add python.exe to PATH"
  echo   ตอนติดตั้ง ให้ติ๊ก "Add python.exe to PATH" ด้วย
  pause
  exit /b 1
)
REM pyproject.toml requires-python = ">=3.11" - a python.exe that merely
REM exists but is too old used to fail deep inside "pip install -e ." with
REM a confusing dependency-resolution error instead of a clear message here.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo [ERROR] Python found but too old / พบ Python แต่เวอร์ชันเก่าเกินไป
  echo This app needs Python 3.11 or newer.
  echo แอปนี้ต้องการ Python 3.11 ขึ้นไป กรุณาติดตั้งจาก https://www.python.org/downloads/
  pause
  exit /b 1
)
echo [OK] Python found.

where tesseract >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Tesseract OCR not found / ไม่พบ Tesseract OCR
  echo Please install it from https://github.com/UB-Mannheim/tesseract/wiki
  echo   During setup, select the Thai language pack.
  echo   ตอนติดตั้ง ให้เลือก Language pack ภาษาไทย ^(Thai^) ด้วย
  echo Then run this file again / แล้วรันไฟล์นี้ใหม่อีกครั้ง
  pause
  exit /b 1
)
echo [OK] Tesseract found.

echo == 2/2 Installing Python dependencies / ติดตั้ง Python dependencies ==
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -e ".[ocr,api,dev]"
if errorlevel 1 (
  echo [ERROR] pip install failed - see the messages above for details.
  echo ติดตั้ง dependencies ไม่สำเร็จ - ดูข้อความด้านบนสำหรับรายละเอียด
  pause
  exit /b 1
)

echo.
echo [DONE] Install complete! / ติดตั้งเสร็จสมบูรณ์!
echo Double-click run.bat to start the app.
echo เปิดใช้งานแอปด้วยการดับเบิลคลิก run.bat
pause
