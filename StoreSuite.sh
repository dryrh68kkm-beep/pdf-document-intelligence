#!/usr/bin/env bash
# Store Suite launcher (macOS / Linux)
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && . .venv/bin/activate && python -m pip install --retries 10 --timeout 60 --disable-pip-version-check -e ".[api,ocr]"; }
. .venv/bin/activate
exec python scripts/run_suite.py
