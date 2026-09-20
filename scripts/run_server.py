"""Windows/local launcher for PDF Document Intelligence.

Writes an ownership PID file, starts Uvicorn on the existing LAN binding,
and opens the browser only after /api/health confirms the server is ready.
This avoids the old race where run.bat opened localhost before Uvicorn had
finished starting.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from pdf_document_intelligence.db.paths import get_data_dir

URL = "http://localhost:8000"
HEALTH_URL = f"{URL}/api/health"


def _app_is_ready(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload, dict) and "database" in payload and "productMaster" in payload
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _chrome_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    return candidates


def _open_browser() -> None:
    for chrome in _chrome_candidates():
        if chrome.is_file():
            subprocess.Popen([str(chrome), URL])
            return
    webbrowser.open(URL)


def _open_when_ready(deadline_seconds: float = 45.0) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if _app_is_ready():
            _open_browser()
            return
        time.sleep(0.25)


def main() -> int:
    # If this app is already serving on the port, do not start a second
    # process; simply bring the existing instance to the user.
    if _app_is_ready():
        _open_browser()
        return 0

    pid_file = get_data_dir() / "server.pid"
    own_pid = str(os.getpid())
    pid_file.write_text(own_pid, encoding="ascii")

    opener = threading.Thread(target=_open_when_ready, name="browser-ready-waiter", daemon=True)
    opener.start()
    try:
        uvicorn.run(
            "pdf_document_intelligence.api.app:app",
            host="0.0.0.0",
            port=8000,
        )
        return 0
    finally:
        try:
            if pid_file.read_text(encoding="ascii").strip() == own_pid:
                pid_file.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
