@echo off
REM เปิดใช้งานแอป PDF Document Intelligence (Windows)
cd /d "%~dp0"

if not exist ".venv" (
  echo ยังไม่ได้ติดตั้ง กรุณาดับเบิลคลิก install.bat ก่อน
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
start "" http://localhost:8000
echo กำลังเปิดแอปที่ http://localhost:8000 (ปิดหน้าต่างนี้เพื่อหยุดเซิร์ฟเวอร์)
uvicorn pdf_document_intelligence.api.app:app --host 0.0.0.0 --port 8000
