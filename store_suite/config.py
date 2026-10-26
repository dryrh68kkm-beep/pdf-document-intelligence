"""User settings (<data dir>/config.json). Missing file or key = default."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from store_suite.paths import get_data_dir

DEFAULTS: dict = {
    # 8100: the standalone apps already use 8000 (PDF), 8080 (Atlas) and 8090 (expiry), so a still-running old app cannot block Store Suite.
    "port": 8100,
    # Only loopback + private LAN addresses may connect (same rule as Stock Atlas).
    "lanOnly": True,
    # Folder the POS drops NEARLY_EXPIRED_* files into (UNC path ok). Empty = off.
    "expirySourceFolder": "",
    "expirySourceBasename": "NEARLY_EXPIRED_1003",
    "expirySourceExtensions": [".csv", ".xlsx", ".txt"],
    # Where the OOS report files are saved (UNC path ok). "{year}" becomes the current year,
    # e.g. \\\\server\\share\\OOS\\{year}\\OOS. Listed in Atlas under "ไฟล์จากโปรแกรมอื่น". Empty = off.
    "oosSourceFolder": "",
    # Extra folders other programs drop OOS / layout files into (Atlas "files from other programs").
    "atlasSources": [],
    # Background sync period; 0 = only when someone presses the sync button.
    "autoSyncMinutes": 10,
}

_lock = threading.Lock()


def config_path() -> Path:
    return get_data_dir() / "config.json"


_cache: dict = {"key": None, "data": {}}


def _file_config() -> dict:
    """config.json parsed once per change - every request checks LAN-only."""
    path = config_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _cache["key"] != key:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        _cache["key"], _cache["data"] = key, data if isinstance(data, dict) else {}
    return _cache["data"]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _file_config().items() if k in DEFAULTS})
    if os.environ.get("STORE_SUITE_PORT", "").isdigit():
        cfg["port"] = int(os.environ["STORE_SUITE_PORT"])
    return cfg


def save_config(patch: dict) -> dict:
    with _lock:
        cfg = load_config()
        cfg.update({k: v for k, v in patch.items() if k in DEFAULTS and k != "port"})
        tmp = config_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({k: cfg[k] for k in DEFAULTS if k != "port"}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(config_path())
        return cfg
