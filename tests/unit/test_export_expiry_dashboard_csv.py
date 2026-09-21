"""build_expiry_dashboard_rows/export_expiry_dashboard_csv (the LP-Tools
expiry-dashboard bridge) must: dedupe by barcode (last write wins), skip
rows with no barcode, and neutralize formula-injection the same way
export/excel.py does - this CSV is opened in Excel by the same users."""
from __future__ import annotations

import csv
import io

from pdf_document_intelligence.export.expiry_dashboard_csv import (
    build_expiry_dashboard_rows,
    export_expiry_dashboard_csv,
)


def _doc(*products: dict) -> dict:
    return {"products": list(products)}


def _product(barcode: str | None, name: str, department: str) -> dict:
    return {
        "fields": {
            "barcode": {"value": barcode} if barcode is not None else None,
            "name": {"value": name},
        },
        "department": department,
    }


def test_dedupes_by_barcode_last_write_wins():
    docs = [
        _doc(_product("123", "Old Name", "CHILLED")),
        _doc(_product("123", "New Name", "DAIRY")),
    ]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == [("123", "New Name", "DAIRY")]


def test_rows_without_a_barcode_are_skipped():
    docs = [_doc(_product(None, "No Barcode", "CHILLED"), _product("999", "Has Barcode", "SAUSAGE"))]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == [("999", "Has Barcode", "SAUSAGE")]


def test_rows_are_sorted_by_barcode():
    docs = [_doc(_product("500", "B", "DAIRY"), _product("100", "A", "CHILLED"))]
    rows = build_expiry_dashboard_rows(docs)
    assert [r[0] for r in rows] == ["100", "500"]


def test_csv_output_has_expected_header_and_neutralizes_formulas():
    docs = [_doc(_product("111", "=HYPERLINK(\"http://evil.example\")", "CHILLED"))]
    csv_bytes = export_expiry_dashboard_csv(docs)
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert rows[0] == ["BAR_CODE", "DESCRIPTION", "SUB_DEPT_NAME"]
    assert rows[1][1].startswith("'=")
