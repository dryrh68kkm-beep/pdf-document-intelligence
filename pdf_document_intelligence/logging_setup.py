"""Makes the app's own logger ("pdf_document_intelligence") write to a
persistent rotating file under the data directory, not only stdout.

User report: finding a 500's server-side traceback (the diagnosticId
printed in the browser) meant catching it live in the terminal window
running run.bat, before it either scrolled past or the window was closed
- the only record of it existed there, for as long as that window stayed
open and un-scrolled. configure_logging() must run once, as early as
possible (before any other module in this app logs anything), so no
error is ever lost to that window again.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from pdf_document_intelligence.db.paths import get_log_path

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    logger = logging.getLogger("pdf_document_intelligence")
    logger.setLevel(logging.INFO)
    # This logger owns its own handlers (file + console) rather than
    # relying on the root logger's configuration (uvicorn sets its own up
    # independently) - propagate=False keeps a message from printing
    # twice if something upstream ever adds a root handler too.
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT)

    # 5MB x 4 files (the current one + 3 rotated backups) is plenty for a
    # single-store desktop deployment's error volume while staying well
    # short of anything a user would need to think about cleaning up.
    file_handler = RotatingFileHandler(get_log_path(), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Unchanged from before this module existed: still visible live in
    # the terminal window too, for anyone watching it in the moment.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
