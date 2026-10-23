"""Where Store Suite keeps its own data (never inside the source tree)."""
from __future__ import annotations

import os
from pathlib import Path

WEB_DIR = Path(__file__).parent / "web"


def get_data_dir() -> Path:
    override = os.environ.get("STORE_SUITE_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "store-suite"
    else:
        base = Path.home() / ".local" / "share" / "store-suite"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(*parts: str) -> Path:
    p = get_data_dir().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def expiry_dir() -> Path:
    """Holds data.csv / data.xlsx / status.json - the same files the
    standalone expiry-dashboard's fetch-data.ps1 writes into its www/."""
    return _sub("expiry", "www")


def atlas_state_dir() -> Path:
    return _sub("atlas", "state")


def atlas_backup_dir() -> Path:
    return _sub("atlas", "state", "backup")


def atlas_inbox_dir() -> Path:
    return _sub("atlas", "inbox")


def atlas_export_dir() -> Path:
    return _sub("atlas", "export")
