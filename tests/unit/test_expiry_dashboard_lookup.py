"""catalog/expiry_dashboard_lookup.py: reads expiry-dashboard's own daily
data.csv/data.xlsx (the same file its www/index.html auto-loads) and
looks up a barcode against it. Must: prefer data.csv over data.xlsx (same
order expiry-dashboard's own tryAutoLoad tries them), read both formats,
return None for an unknown barcode or a missing file, re-read the file
when it changes on disk (it's rewritten fresh every day), and - the whole
point of catalog/expiry_dashboard_snapshot.py - keep a barcode resolvable
even after it drops out of the live file entirely.

Every test passes its own snapshot_path under tmp_path so these never
touch the real app data directory (get_data_dir()'s default)."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from pdf_document_intelligence.catalog.expiry_dashboard_lookup import (
    load_expiry_dashboard_index,
    lookup_barcode,
    resolve_data_path,
)

CSV_TEXT = "BAR_CODE,DESCRIPTION,SUB_DEPT_NAME,STOCK_QTY\n8850000000001,Perrier 1500ml,CHILLED,5\n"


def _snapshot(tmp_path: Path) -> Path:
    return tmp_path / "snapshot" / "expiry_dashboard.snapshot.json"


def test_resolve_data_path_prefers_csv_over_xlsx(tmp_path: Path):
    (tmp_path / "data.csv").write_text(CSV_TEXT, encoding="utf-8")
    (tmp_path / "data.xlsx").write_bytes(b"not a real xlsx but presence is enough")
    assert resolve_data_path(str(tmp_path)) == tmp_path / "data.csv"


def test_resolve_data_path_falls_back_to_xlsx(tmp_path: Path):
    (tmp_path / "data.xlsx").write_bytes(b"placeholder")
    assert resolve_data_path(str(tmp_path)) == tmp_path / "data.xlsx"


def test_resolve_data_path_returns_none_when_neither_exists(tmp_path: Path):
    assert resolve_data_path(str(tmp_path)) is None


def test_resolve_data_path_returns_none_for_empty_dir_setting():
    assert resolve_data_path("") is None


def test_lookup_barcode_finds_a_known_row_in_csv(tmp_path: Path):
    path = tmp_path / "data.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    entry = lookup_barcode("8850000000001", path, _snapshot(tmp_path))
    assert entry == {"description": "Perrier 1500ml", "sub_dept_name": "CHILLED"}


def test_lookup_barcode_returns_none_for_unknown_barcode(tmp_path: Path):
    path = tmp_path / "data.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    assert lookup_barcode("9999999999999", path, _snapshot(tmp_path)) is None


def test_lookup_barcode_returns_none_when_path_is_none(tmp_path: Path):
    assert lookup_barcode("8850000000001", None, _snapshot(tmp_path)) is None


def test_lookup_barcode_returns_none_when_file_is_missing(tmp_path: Path):
    assert lookup_barcode("8850000000001", tmp_path / "data.csv", _snapshot(tmp_path)) is None


def test_reads_xlsx_format(tmp_path: Path):
    path = tmp_path / "data.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["BAR_CODE", "DESCRIPTION", "SUB_DEPT_NAME"])
    ws.append(["8850000000002", "Evian 500ml", "DAIRY"])
    wb.save(path)
    entry = lookup_barcode("8850000000002", path, _snapshot(tmp_path))
    assert entry == {"description": "Evian 500ml", "sub_dept_name": "DAIRY"}


def test_index_is_rebuilt_after_the_file_changes(tmp_path: Path):
    path = tmp_path / "data.csv"
    snapshot = _snapshot(tmp_path)
    path.write_text(CSV_TEXT, encoding="utf-8")
    first = load_expiry_dashboard_index(path, snapshot)
    assert "8850000000001" in first
    assert "8850000000009" not in first

    path.write_text(CSV_TEXT + "8850000000009,New Item,DAIRY,1\n", encoding="utf-8")
    second = load_expiry_dashboard_index(path, snapshot)
    assert "8850000000009" in second


def test_a_barcode_survives_after_it_drops_out_of_the_live_file(tmp_path: Path):
    """The whole point of the persistent snapshot: expiry-dashboard's file
    only lists TODAY's near-expiry items, so a barcode confirmed
    yesterday is expected to vanish from it - that must not make this
    lookup forget the product."""
    path = tmp_path / "data.csv"
    snapshot = _snapshot(tmp_path)
    path.write_text(CSV_TEXT, encoding="utf-8")
    assert lookup_barcode("8850000000001", path, snapshot) is not None

    # Today's file no longer carries that barcode at all.
    path.write_text("BAR_CODE,DESCRIPTION,SUB_DEPT_NAME,STOCK_QTY\n9990000000000,Other Item,DAIRY,1\n", encoding="utf-8")
    still_there = lookup_barcode("8850000000001", path, snapshot)
    assert still_there == {"description": "Perrier 1500ml", "sub_dept_name": "CHILLED"}


def test_a_barcode_survives_when_the_live_file_disappears_entirely(tmp_path: Path):
    path = tmp_path / "data.csv"
    snapshot = _snapshot(tmp_path)
    path.write_text(CSV_TEXT, encoding="utf-8")
    assert lookup_barcode("8850000000001", path, snapshot) is not None

    path.unlink()
    still_there = lookup_barcode("8850000000001", path, snapshot)
    assert still_there == {"description": "Perrier 1500ml", "sub_dept_name": "CHILLED"}


def test_snapshot_persists_to_disk_across_process_restarts(tmp_path: Path):
    """load_expiry_dashboard_index/lookup_barcode hold an in-memory cache,
    but the durable guarantee is the on-disk snapshot file itself -
    simulate a restart by reading straight from load_snapshot()."""
    from pdf_document_intelligence.catalog.expiry_dashboard_snapshot import load_snapshot

    path = tmp_path / "data.csv"
    snapshot = _snapshot(tmp_path)
    path.write_text(CSV_TEXT, encoding="utf-8")
    lookup_barcode("8850000000001", path, snapshot)

    on_disk = load_snapshot(snapshot)
    assert on_disk.get("8850000000001") == {"description": "Perrier 1500ml", "sub_dept_name": "CHILLED"}
