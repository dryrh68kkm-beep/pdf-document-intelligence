@echo off
REM ติดตั้งแอป PDF Document Intelligence แบบอัตโนมัติ (Windows)
cd /d "%~dp0"

echo == 1/2 ตรวจสอบ Python ==
where python >nul 2>nul
if errorlevel 1 (
  echo ไม่พบ Python กรุณาติดตั้งจาก https://www.python.org/downloads/ ก่อน
  echo   (ตอนติดตั้ง ให้ติ๊ก "Add python.exe to PATH" ด้วย)
  pause
  exit /b 1
)

where tesseract >nul 2>nul
if errorlevel 1 (
  echo ไม่พบ Tesseract OCR
  echo กรุณาติดตั้งจาก https://github.com/UB-Mannheim/tesseract/wiki
  echo   ตอนติดตั้ง ให้เลือก Language pack ภาษาไทย ^(Thai^) ด้วย
  echo แล้วรันไฟล์นี้ใหม่อีกครั้ง
  pause
  exit /b 1
)

echo == 2/2 ติดตั้ง Python dependencies ==
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -e ".[ocr,api,dev]"

echo.
echo ติดตั้งเสร็จสมบูรณ์!
echo เปิดใช้งานแอปด้วยการดับเบิลคลิก run.bat
pause
