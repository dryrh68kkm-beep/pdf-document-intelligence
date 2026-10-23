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
    for _ in range(90):
        try:
            with urllib.request.urlopen(url + "/api/suite/health", timeout=1) as r:
                if json.load(r).get("ok"):
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            time.sleep(0.5)


def main() -> None:
    cfg = load_config()
    port = int(cfg["port"])
    threading.Thread(target=_wait_and_open, args=(f"http://localhost:{port}",), daemon=True).start()
    uvicorn.run("store_suite.app:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
