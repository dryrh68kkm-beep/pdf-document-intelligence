"""Resolves where the app's local, offline data lives.

Priority: PDF_INTELLIGENCE_DATA_DIR env var (explicit override) -> a
platform-appropriate local application data directory. Never hard-coded to
an absolute path, and never touches the network - this is purely local
filesystem resolution so the app keeps working with zero internet access.

The Auto PDF Folder Import watch directory (get_inbox_dir()) has its own,
separate override - PDF_INTELLIGENCE_INBOX_DIR - so a user can point the
watcher at an existing folder they already drop PDFs into (e.g. a shared
Desktop folder from a legacy workflow) without relocating the whole app
data directory (database, PDF storage, backups) to live there too.
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
    # Auto PDF Folder Import watch directory - created here (not lazily by
    # the watcher itself) so it always exists the moment the app resolves
    # its data dir at all, same as pdfs/backups above, and a user can drop
    # a file into it even before the watcher's first scan runs.
    (data_dir / "inbox").mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    return get_data_dir() / "app.db"


def get_pdf_path(document_id: str) -> Path:
    return get_data_dir() / "pdfs" / f"{document_id}.pdf"


def get_inbox_dir() -> Path:
    """Where Auto PDF Folder Import watches for dropped-in PDFs.

    PDF_INTELLIGENCE_INBOX_DIR, when set, points the watcher at a folder
    outside the app's own data directory entirely - a user's existing
    "drop PDFs here" folder (e.g. on their Desktop) rather than the app's
    default data/inbox. Created on first resolution if it doesn't exist
    yet, same as every other directory this module resolves - the user
    never has to create it by hand before pointing the app at it."""
    override = os.environ.get("PDF_INTELLIGENCE_INBOX_DIR")
    if override:
        inbox_dir = Path(override)
        inbox_dir.mkdir(parents=True, exist_ok=True)
        return inbox_dir
    return get_data_dir() / "inbox"
