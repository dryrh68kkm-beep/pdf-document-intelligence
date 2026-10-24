"""Launcher for Store Suite: start the one server, open the browser when ready."""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from store_suite.config import load_config
from store_suite.paths import get_data_dir


def _wait_and_open(url: str) -> None:
    # 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 first and
    # the server listens on IPv4, which adds a stall to every attempt.
    # First start can be slow (antivirus scanning the freshly installed
    # packages), so wait up to 3 minutes instead of giving up early.
    print("Starting - the browser opens by itself when ready (first start can take a minute)...", flush=True)
    for _ in range(360):
        try:
            with urllib.request.urlopen(url + "/api/suite/health", timeout=2) as r:
                if json.load(r).get("ok"):
                    print(f"Ready: {url}", flush=True)
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            time.sleep(0.5)
    print(f"Still not ready - open {url} yourself once the log below says 'Application startup complete'.", flush=True)


def _already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/suite/health", timeout=2) as r:
            return bool(json.load(r).get("ok"))
    except (OSError, ValueError):
        return False


def main() -> None:
    cfg = load_config()
    port = int(cfg["port"])
    url = f"http://127.0.0.1:{port}"
    if _already_running(url):  # double-clicked twice: just show the running one
        webbrowser.open(url)
        return
    if sys.stdout is None or sys.stderr is None:  # pythonw (Desktop shortcut): no console, so log to a file
        log = open(get_data_dir() / "last-run.log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    pid_file = get_data_dir() / "server.pid"
    pid_file.write_text(str(os.getpid()))
    atexit.register(lambda: pid_file.unlink(missing_ok=True))
    threading.Thread(target=_wait_and_open, args=(url,), daemon=True).start()
    uvicorn.run("store_suite.app:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
