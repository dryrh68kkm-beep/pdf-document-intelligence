"""Auto PDF Folder Import: watches data/inbox for new PDFs and feeds each
one through the exact same processing pipeline api/app.py's upload_document()
uses for a manual "Add Files" upload - this module contains no OCR/parser/
import logic of its own, only the filesystem-watching and dedup-decision
layer in front of that existing pipeline (injected in via two small
callbacks so this stays framework-agnostic and unit-testable without a
running FastAPI app or a real background thread).

Dedup rule: a file is skipped forever (until its own bytes actually change)
the moment *any* row in `documents` - active, completed, errored, or
soft-deleted - already carries its sha256. A soft-deleted document's row
keeps its sha256 (db/repository.py's own documented reasoning: correction
history stays inspectable rather than being hard-deleted), which is exactly
what lets this reuse the existing table as the "the user removed this,
don't re-import it" memory the feature needs, with no separate ignore-list
table to keep in sync. Restart survival falls out of the same rule for
free: `documents` is SQLite-backed, so a file already imported before a
restart is still represented there when the watcher's first post-restart
scan re-hashes it.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_logger = logging.getLogger("pdf_document_intelligence")

_HASH_CHUNK_SIZE = 1024 * 1024


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _FileState:
    size: int
    mtime: float
    stable_count: int = 1
    sha256: str | None = None
    # True once this exact (name, size, mtime) has been fully accounted
    # for - either genuinely imported, or found to already have a row in
    # `documents` (imported earlier, or previously deleted). A file whose
    # size/mtime later change resets to a fresh _FileState entirely (see
    # scan_once), so this never has to be un-set by hand.
    resolved: bool = False


class InboxWatcher:
    """`inbox_dir` is scanned for `*.pdf` files (case-insensitive suffix
    match) each time `scan_once()` runs - called on a timer by `start()`'s
    background thread, or directly by a test with no timer involved at
    all.

    `find_any_by_sha256(sha256) -> dict | None` and
    `ingest_new_file(sha256, filename, file_size, source_path) -> dict |
    None` are injected rather than imported directly, so this module
    never has to import api/app.py's executor/store/queue-cap machinery
    (avoiding a circular import) and so tests can exercise the scanning/
    stability/dedup logic here with plain fakes instead of a running
    server. `ingest_new_file` returning None means "not admitted this
    round" (the processing-queue cap was full, or a concurrent manual
    upload of the same bytes won the race) - scan_once() deliberately
    leaves that file unresolved so the very next scan retries it, per the
    feature's own "never lose a file, never duplicate one" requirement.
    """

    def __init__(
        self,
        inbox_dir: Path,
        find_any_by_sha256: Callable[[str], dict | None],
        ingest_new_file: Callable[[str, str, int, Path], dict | None],
        scan_interval_seconds: float = 7.0,
        stability_rounds: int = 2,
        max_file_size_bytes: int = 200 * 1024 * 1024,
    ) -> None:
        self._inbox_dir = inbox_dir
        self._find_any_by_sha256 = find_any_by_sha256
        self._ingest_new_file = ingest_new_file
        self._scan_interval_seconds = scan_interval_seconds
        self._stability_rounds = max(2, stability_rounds)
        self._max_file_size_bytes = max(1, int(max_file_size_bytes))
        self._states: dict[str, _FileState] = {}
        # Guards both _states and the body of scan_once() - the background
        # thread and a caller triggering an out-of-band scan_once() (or two
        # start()s by mistake) must never run two scans over the same
        # directory concurrently, which is exactly what would let a single
        # file get double-imported.
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.last_scan_at: str | None = None
        self.last_error: str | None = None

    @property
    def inbox_dir(self) -> Path:
        return self._inbox_dir

    @property
    def is_watching(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="inbox-watcher", daemon=True)
        self._thread.start()

    def reset_for_tests(self) -> None:
        """Test-only: clears this watcher's in-memory per-filename
        bookkeeping (stability counts, cached hashes, resolved flags).
        The module-level `inbox_watcher` in api/app.py is a singleton
        constructed once at import time and shared across the whole test
        session (matching DocumentStore.reset_for_tests()'s own reasoning
        for the equivalent problem) - without this, a filename reused
        across two otherwise-isolated tests could inherit stale state left
        over from an earlier test instead of starting fresh."""
        with self._lock:
            self._states.clear()
            self.last_scan_at = None
            self.last_error = None

    def stop(self) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001 - one bad scan must not kill the watcher thread
                _logger.exception("Inbox watcher scan failed")
            self._stop_event.wait(self._scan_interval_seconds)

    def scan_once(self) -> None:
        with self._lock:
            self.last_scan_at = _now_iso()
            if not self._inbox_dir.is_dir():
                try:
                    self._inbox_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    self.last_error = "folder_unavailable"
                    return
            current_names: set[str] = set()
            try:
                entries = sorted(self._inbox_dir.iterdir())
            except OSError:
                self.last_error = "folder_unavailable"
                return
            self.last_error = None
            for path in entries:
                if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".pdf":
                    continue
                current_names.add(path.name)
                self._scan_one_file(path)
            # Forget bookkeeping for names no longer in the folder - a
            # later file that reuses the same name must never inherit a
            # stale hash/resolution computed for different bytes.
            for stale_name in set(self._states) - current_names:
                del self._states[stale_name]

    def _scan_one_file(self, path: Path) -> None:
        try:
            stat = path.stat()
        except OSError:
            return  # vanished between iterdir() and stat() - next scan picks it back up if it's still there

        state = self._states.get(path.name)
        if state is None or state.size != stat.st_size or state.mtime != stat.st_mtime:
            # New name, or its size/modified-time changed since last seen
            # (still being written or copied into place) - (re)start the
            # stability count from scratch. A prior hash/resolution, if
            # any, was for different bytes and must not carry over.
            self._states[path.name] = _FileState(size=stat.st_size, mtime=stat.st_mtime)
            return

        state.stable_count += 1
        if state.resolved:
            return
        if state.stable_count < self._stability_rounds:
            return  # not yet unchanged across enough consecutive scans - could still be mid-copy

        # Match the manual Add Files guardrails before hashing/copying a
        # folder drop. Invalid files become resolved for this exact
        # size/mtime and are reconsidered automatically if the user
        # replaces or edits them later.
        if stat.st_size <= 0:
            _logger.warning("Inbox watcher: ignoring empty PDF candidate %s", path.name)
            state.resolved = True
            return
        if stat.st_size > self._max_file_size_bytes:
            _logger.warning(
                "Inbox watcher: ignoring oversized PDF candidate %s (%d bytes)",
                path.name,
                stat.st_size,
            )
            state.resolved = True
            return
        try:
            with path.open("rb") as source:
                header = source.read(5)
        except OSError:
            return
        if header != b"%PDF-":
            _logger.warning("Inbox watcher: ignoring file with invalid PDF signature: %s", path.name)
            state.resolved = True
            return

        if state.sha256 is None:
            try:
                state.sha256 = _sha256_file(path)
            except OSError:
                return  # unreadable right now (still locked by whatever's writing it) - retry next scan

        existing = self._find_any_by_sha256(state.sha256)
        if existing is not None:
            state.resolved = True
            return

        doc = self._ingest_new_file(state.sha256, path.name, stat.st_size, path)
        if doc is not None:
            state.resolved = True
        else:
            # The source may have changed in the tiny window between our
            # hash and the app-managed copy. Force a fresh hash before a
            # retry; this also keeps a queue-full retry correct (at the
            # cost of one extra sequential read while the queue is full).
            state.sha256 = None
        # else: leave resolved False - queue was full or a concurrent
        # upload of the same bytes won the race; the next scan re-checks
        # find_any_by_sha256 first (cheap) before ever attempting another
        # ingest, so this never risks a duplicate on retry.
