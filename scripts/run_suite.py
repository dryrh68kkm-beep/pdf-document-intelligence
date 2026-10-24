"""Launcher for Store Suite: start the one server, open the browser when ready."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from store_suite.config import load_config


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


def main() -> None:
    cfg = load_config()
    port = int(cfg["port"])
    threading.Thread(target=_wait_and_open, args=(f"http://127.0.0.1:{port}",), daemon=True).start()
    uvicorn.run("store_suite.app:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
