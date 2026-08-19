"""Resolves where the app's local, offline data lives.

Priority: PDF_INTELLIGENCE_DATA_DIR env var (explicit override) -> a
platform-appropriate local application data directory. Never hard-coded to
an absolute path, and never touches the network - this is purely local
filesystem resolution so the app keeps working with zero internet access.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "pdf-document-intelligence"


def _platform_default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_DIR_NAME


def get_data_dir() -> Path:
    override = os.environ.get("PDF_INTELLIGENCE_DATA_DIR")
    data_dir = Path(override) if override else _platform_default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    (data_dir / "backups").mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    return get_data_dir() / "app.db"


def get_pdf_path(document_id: str) -> Path:
    return get_data_dir() / "pdfs" / f"{document_id}.pdf"
