"""Persistent, accumulating snapshot of every barcode this pipeline has
ever seen confirmed in expiry-dashboard's own live daily export.

expiry-dashboard's data.csv/data.xlsx only ever lists *today's*
near-expiry items - a barcode present yesterday can be completely absent
today (sold through, or simply no longer near expiry), not because it
stopped being a real product. Relying on a live read of that file alone
(catalog/expiry_dashboard_lookup.py's _build_index) would make a
previously-confirmed match silently disappear the moment that barcode
isn't in today's export. This module merges every live read into a
private JSON file under PDF_INTELLIGENCE_DATA_DIR (upsert only, by
barcode, same atomic-write approach as catalog/snapshot.py) so a barcode
learned once stays resolvable even after it drops out of
expiry-dashboard's file entirely.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pdf_document_intelligence.db.paths import get_data_dir

SNAPSHOT_FILENAME = "expiry_dashboard.snapshot.json"
SNAPSHOT_VERSION = 1


def get_snapshot_path() -> Path:
    return get_data_dir() / SNAPSHOT_FILENAME


def load_snapshot(snapshot_path: Path | None = None) -> dict[str, dict[str, str]]:
    path = snapshot_path or get_snapshot_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
        return {}
    entries = payload.get("entries")
    return entries if isinstance(entries, dict) else {}


def _write_snapshot(entries: dict[str, dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SNAPSHOT_VERSION, "entries": entries}
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        Path(temp_name).replace(path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def merge_into_snapshot(
    new_entries: dict[str, dict[str, str]], snapshot_path: Path | None = None
) -> dict[str, dict[str, str]]:
    """Upsert-only merge: an entry the live file re-confirms today is
    updated (name/sub-dept may have changed), and an entry the live file
    no longer carries is left exactly as it was - never dropped. Skips
    the write entirely when nothing actually changed, so a barcode
    already-known and re-read unchanged today doesn't churn the file."""
    path = snapshot_path or get_snapshot_path()
    current = load_snapshot(path)
    if not new_entries:
        return current
    merged = {**current, **new_entries}
    if merged == current:
        return current
    _write_snapshot(merged, path)
    return merged
