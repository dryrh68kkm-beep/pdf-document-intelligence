"""User settings (<data dir>/config.json). Missing file or key = default."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from store_suite.paths import get_data_dir

DEFAULTS: dict = {
    "port": 8000,
    # Only loopback + private LAN addresses may connect (same rule as Stock Atlas).
    "lanOnly": True,
    # Folder the POS drops NEARLY_EXPIRED_* files into (UNC path ok). Empty = off.
    "expirySourceFolder": "",
    "expirySourceBasename": "NEARLY_EXPIRED_1003",
    "expirySourceExtensions": [".csv", ".xlsx", ".txt"],
    # Extra folders other programs drop OOS / layout files into (Atlas "files from other programs").
    "atlasSources": [],
    # Background sync period; 0 = only when someone presses the sync button.
    "autoSyncMinutes": 10,
}

_lock = threading.Lock()


def config_path() -> Path:
    return get_data_dir() / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(config_path().read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
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
