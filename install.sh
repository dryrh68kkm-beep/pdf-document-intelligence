#!/usr/bin/env bash
# ติดตั้งแอป PDF Document Intelligence แบบอัตโนมัติ (macOS / Linux)
set -e
cd "$(dirname "$0")"

echo "== 1/3 ตรวจสอบ Python =="
if ! command -v python3 >/dev/null 2>&1; then
  echo "ไม่พบ python3 กรุณาติดตั้ง Python 3.11+ ก่อน: https://www.python.org/downloads/"
  exit 1
fi

echo "== 2/3 ตรวจสอบ Tesseract OCR (ภาษาไทย) =="
if ! command -v tesseract >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "ไม่พบ tesseract กำลังติดตั้งด้วย apt-get (อาจถามรหัสผ่าน sudo)..."
    sudo apt-get update -qq && sudo apt-get install -y tesseract-ocr tesseract-ocr-tha
  elif command -v brew >/dev/null 2>&1; then
    echo "ไม่พบ tesseract กำลังติดตั้งด้วย Homebrew..."
    brew install tesseract tesseract-lang
  else
    echo "ไม่พบ tesseract และไม่พบ apt-get/brew ให้ติดตั้งเอง แล้วรันสคริปต์นี้ใหม่:"
    echo "  https://tesseract-ocr.github.io/tessdoc/Installation.html"
    exit 1
  fi
else
  echo "พบ tesseract แล้ว ข้ามขั้นตอนนี้"
fi

echo "== 3/3 ติดตั้ง Python dependencies =="
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[ocr,api,dev]"

echo ""
echo "ติดตั้งเสร็จสมบูรณ์!"
echo "เปิดใช้งานแอปด้วยคำสั่ง: ./run.sh"
