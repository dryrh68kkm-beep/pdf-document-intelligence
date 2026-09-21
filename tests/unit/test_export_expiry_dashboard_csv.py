"""build_expiry_dashboard_rows/export_expiry_dashboard_csv (the LP-Tools
expiry-dashboard bridge) must: dedupe by barcode (last write wins), skip
rows with no barcode, skip rows still pending manual review, carry
through the master-catalog unit_price, and neutralize formula-injection
the same way export/excel.py does - this CSV is opened in Excel by the
same users."""
from __future__ import annotations

import csv
import io

from pdf_document_intelligence.export.expiry_dashboard_csv import (
    build_expiry_dashboard_rows,
    export_expiry_dashboard_csv,
)


def _doc(*products: dict) -> dict:
    return {"products": list(products)}


def _product(
    barcode: str | None,
    name: str,
    department: str,
    unit_price: float | None = None,
    review_required: bool = False,
) -> dict:
    return {
        "fields": {
            "barcode": {"value": barcode} if barcode is not None else None,
            "name": {"value": name},
            "unit_price": {"value": unit_price} if unit_price is not None else None,
        },
        "department": department,
        "reviewRequired": review_required,
    }


def test_dedupes_by_barcode_last_write_wins():
    docs = [
        _doc(_product("123", "Old Name", "CHILLED", 10.5)),
        _doc(_product("123", "New Name", "DAIRY", 12.0)),
    ]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == [("123", "New Name", "DAIRY", 12.0)]


def test_rows_without_a_barcode_are_skipped():
    docs = [_doc(_product(None, "No Barcode", "CHILLED"), _product("999", "Has Barcode", "SAUSAGE"))]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == [("999", "Has Barcode", "SAUSAGE", None)]


def test_rows_are_sorted_by_barcode():
    docs = [_doc(_product("500", "B", "DAIRY"), _product("100", "A", "CHILLED"))]
    rows = build_expiry_dashboard_rows(docs)
    assert [r[0] for r in rows] == ["100", "500"]


def test_missing_unit_price_stays_none():
    docs = [_doc(_product("111", "No Price", "CHILLED"))]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == [("111", "No Price", "CHILLED", None)]


def test_csv_output_has_expected_header_and_neutralizes_formulas():
    docs = [_doc(_product("111", "=HYPERLINK(\"http://evil.example\")", "CHILLED", 9.99))]
    csv_bytes = export_expiry_dashboard_csv(docs)
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert rows[0] == ["BAR_CODE", "DESCRIPTION", "SUB_DEPT_NAME", "UNIT_PRICE"]
    assert rows[1][1].startswith("'=")
    assert rows[1][3] == "9.99"


def test_csv_output_leaves_missing_price_blank():
    docs = [_doc(_product("222", "No Price Item", "DAIRY"))]
    csv_bytes = export_expiry_dashboard_csv(docs)
    reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    rows = list(reader)
    assert rows[1][3] == ""


def test_rows_still_pending_review_are_excluded():
    docs = [_doc(_product("333", "Unverified", "CHILLED", review_required=True))]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == []


def test_a_confirmed_reading_in_one_doc_wins_over_a_pending_one_in_another():
    docs = [
        _doc(_product("444", "Unverified Guess", "CHILLED", review_required=True)),
        _doc(_product("444", "Confirmed Name", "DAIRY", review_required=False)),
    ]
    rows = build_expiry_dashboard_rows(docs)
    assert rows == [("444", "Confirmed Name", "DAIRY", None)]
