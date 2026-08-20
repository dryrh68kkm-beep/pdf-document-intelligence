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

# Serializes every write transaction against this module's connection(s).
# Reproduced (L3-001): two threads racing a `with conn:` block on the same
# shared sqlite3.Connection - the background OCR thread pool writing
# progress/results concurrently with an API request thread writing a
# correction/upload/delete - can raise "OperationalError: cannot start a
# transaction within a transaction". This isn't a lock-contention timing
# issue busy_timeout fixes (that's for a second connection waiting on a
# held lock at the SQLite level); it's Python's sqlite3 module tracking
# "am I in a transaction" as connection-level state that two threads can
# race on directly. A single process-wide lock around every write
# transaction is the same protection the pre-SQLite in-memory store used
# to have (a plain threading.Lock) before that got dropped in the
# migration - restored here at the write-transaction boundary instead of
# per-dict-access, since a Repository's job is now a bundle of SQL
# statements rather than a single dict mutation.
_write_lock = threading.Lock()


def get_write_lock() -> threading.Lock:
    return _write_lock


def _configure(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Default busy_timeout is 0 - a second writer (the background OCR
    # thread pool and an API request thread both write through this same
    # connection, see db/connection.py module docstring) gets an immediate
    # "database is locked" OperationalError instead of a brief wait.
    # Reproduced: two threads writing concurrently without this pragma set
    # raised OperationalError on the second one every time.
    conn.execute("PRAGMA busy_timeout=5000")
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
