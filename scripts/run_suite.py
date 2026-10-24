"""Launcher for Store Suite: start the one server, open the browser when ready."""
from __future__ import annotations

import sys

if sys.stdout is None or sys.stderr is None:  # pythonw: no console, so everything - even import errors - goes to a log file
    import os as _os
    import pathlib as _pl

    _d = _pl.Path(_os.environ.get("STORE_SUITE_DATA_DIR") or (_pl.Path(_os.environ.get("LOCALAPPDATA", _pl.Path.home())) / "store-suite"))
    _d.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(_d / "last-run.log", "w", encoding="utf-8", buffering=1)

import atexit
import json
import os
import socket
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


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/suite/health", timeout=2) as r:
            return bool(json.load(r).get("ok"))
    except (OSError, ValueError):
        return False


def main() -> None:
    cfg = load_config()
    first = int(cfg["port"])
    for port in range(first, first + 21):
        url = f"http://127.0.0.1:{port}"
        if _already_running(url):  # double-clicked twice: just show the running one
            print(f"Store Suite is already running: {url}", flush=True)
            webbrowser.open(url)
            return
        if _port_free(port):
            break
        print(f"Port {port} is used by another program - trying the next one...", flush=True)
    else:
        print(f"No free port between {first} and {first + 20}. Close other programs and try again.", flush=True)
        input("Press Enter to close")
        return
    (get_data_dir() / "server.port").write_text(str(port))
    pid_file = get_data_dir() / "server.pid"
    pid_file.write_text(str(os.getpid()))
    atexit.register(lambda: pid_file.unlink(missing_ok=True))
    threading.Thread(target=_wait_and_open, args=(url,), daemon=True).start()
    print(f"Store Suite: {url}   (keep this window open; Ctrl+C to stop)", flush=True)
    uvicorn.run("store_suite.app:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
