"""catalog/expiry_dashboard_snapshot.py: the persistent, accumulating
barcode store behind the expiry-dashboard reverse lookup. Must: return {}
for a missing/corrupt file, merge upsert-only (never drop an entry the
new read didn't mention), and survive being read back as a fresh load
(simulating a process restart)."""
from __future__ import annotations

from pathlib import Path

from pdf_document_intelligence.catalog.expiry_dashboard_snapshot import (
    load_snapshot,
    merge_into_snapshot,
)


def _snapshot(tmp_path: Path) -> Path:
    return tmp_path / "expiry_dashboard.snapshot.json"


def test_load_snapshot_returns_empty_dict_when_file_is_missing(tmp_path: Path):
    assert load_snapshot(_snapshot(tmp_path)) == {}


def test_load_snapshot_returns_empty_dict_for_corrupt_json(tmp_path: Path):
    path = _snapshot(tmp_path)
    path.write_text("not json", encoding="utf-8")
    assert load_snapshot(path) == {}


def test_merge_writes_new_entries_to_disk(tmp_path: Path):
    path = _snapshot(tmp_path)
    merge_into_snapshot({"111": {"description": "A", "sub_dept_name": "CHILLED"}}, path)
    assert load_snapshot(path) == {"111": {"description": "A", "sub_dept_name": "CHILLED"}}


def test_merge_is_upsert_only_and_never_drops_existing_entries(tmp_path: Path):
    path = _snapshot(tmp_path)
    merge_into_snapshot({"111": {"description": "A", "sub_dept_name": "CHILLED"}}, path)
    merge_into_snapshot({"222": {"description": "B", "sub_dept_name": "DAIRY"}}, path)
    assert load_snapshot(path) == {
        "111": {"description": "A", "sub_dept_name": "CHILLED"},
        "222": {"description": "B", "sub_dept_name": "DAIRY"},
    }


def test_merge_updates_an_existing_entry_when_re_confirmed_with_new_data(tmp_path: Path):
    path = _snapshot(tmp_path)
    merge_into_snapshot({"111": {"description": "Old Name", "sub_dept_name": "CHILLED"}}, path)
    merge_into_snapshot({"111": {"description": "New Name", "sub_dept_name": "DAIRY"}}, path)
    assert load_snapshot(path) == {"111": {"description": "New Name", "sub_dept_name": "DAIRY"}}


def test_merge_with_no_new_entries_is_a_no_op(tmp_path: Path):
    path = _snapshot(tmp_path)
    merge_into_snapshot({"111": {"description": "A", "sub_dept_name": "CHILLED"}}, path)
    result = merge_into_snapshot({}, path)
    assert result == {"111": {"description": "A", "sub_dept_name": "CHILLED"}}
