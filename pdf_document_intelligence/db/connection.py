"""Single-process SQLite connection factory. Desktop-local, single-writer
app - one long-lived connection in WAL mode is enough; no connection pool
needed (spec: offline, no DB server, one file).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from pdf_document_intelligence.db.migrations import run_migrations
from pdf_document_intelligence.db.paths import get_db_path

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _configure(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = db_path or get_db_path()
            _conn = sqlite3.connect(str(path), check_same_thread=False)
            _configure(_conn)
            run_migrations(_conn)
        return _conn


def reset_connection_for_tests(db_path: Path) -> sqlite3.Connection:
    """Test-only: force the *shared singleton* (the one `store`/the FastAPI
    app actually use) to reopen against a fresh DB file - for tests that
    simulate a real application restart end-to-end through the API."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _configure(_conn)
        run_migrations(_conn)
        return _conn


def open_independent_connection(db_path: Path) -> sqlite3.Connection:
    """Test-only: an isolated connection bound to its own DB file, entirely
    separate from the shared singleton `get_connection()` returns - for
    repository-level unit tests that must not disturb the app's own live
    connection when many test modules run in the same process."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _configure(conn)
    run_migrations(conn)
    return conn
