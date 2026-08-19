#!/usr/bin/env bash
# เปิดใช้งานแอป PDF Document Intelligence (macOS / Linux)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "ยังไม่ได้ติดตั้ง กรุณารัน ./install.sh ก่อน"
  exit 1
fi

source .venv/bin/activate

# เปิดเบราว์เซอร์อัตโนมัติหลังเซิร์ฟเวอร์พร้อม
( sleep 2
  URL="http://localhost:8000"
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi
) &

echo "กำลังเปิดแอปที่ http://localhost:8000 (กด Ctrl+C เพื่อปิด)"
uvicorn pdf_document_intelligence.api.app:app --host 0.0.0.0 --port 8000
