"""Master-data feed for the expiry-dashboard project (LP-Tools).

expiry-dashboard's daily NEARLY_EXPIRED import already carries its own
STOCK_QTY/DAY_LEFT/DIV/DEPT (numeric codes from the store's POS) - a
delivery document has no on-hand stock or expiry data, and this tool has
no source for those numeric division/department codes, so this export
does not attempt either. What it can give, because every packing list row
is already matched against the master catalog
(templates/department_groups.py, api/rows.py's unit_price/CURRENT_COST
lookup), is a clean barcode -> description/sub-department/unit-price
lookup - sub-department at the same granularity as expiry-dashboard's own
SUB_DEPT_NAME column (e.g. CHILLED, SAUSAGE, DAIRY), unit price from the
same master-catalog cost figure the frontend's Evidence panel already
shows. The dashboard's auto-fetch enrichment joins this onto barcodes
whose DESCRIPTION/SUB_DEPT_NAME/UNIT_PRICE the POS export left blank,
instead of a second hand-maintained mapping.
"""
from __future__ import annotations

import csv
import io

HEADER = ("BAR_CODE", "DESCRIPTION", "SUB_DEPT_NAME", "UNIT_PRICE")

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: str) -> str:
    """Same formula-injection guard as export/excel.py - this CSV is opened
    in Excel by the same store users, from the same untrusted PDF/OCR text."""
    if value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def build_expiry_dashboard_rows(docs: list[dict]) -> list[tuple[str, str, str, float | None]]:
    """One row per distinct barcode across all completed documents, last
    write wins on a repeated barcode (a later delivery's naming is the
    more current one)."""
    by_barcode: dict[str, tuple[str, str, str, float | None]] = {}
    for doc in docs:
        for product in doc.get("products", []):
            barcode_field = product["fields"].get("barcode")
            name_field = product["fields"].get("name")
            price_field = product["fields"].get("unit_price")
            barcode = barcode_field["value"] if barcode_field else None
            if not barcode:
                continue
            name = (name_field["value"] if name_field else "") or ""
            sub_dept = product.get("department") or ""
            unit_price = price_field["value"] if price_field else None
            by_barcode[str(barcode)] = (str(barcode), str(name), sub_dept, unit_price)
    return [by_barcode[k] for k in sorted(by_barcode)]


def export_expiry_dashboard_csv(docs: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(HEADER)
    for barcode, name, sub_dept, unit_price in build_expiry_dashboard_rows(docs):
        writer.writerow([_safe(barcode), _safe(name), _safe(sub_dept), unit_price if unit_price is not None else ""])
    return buf.getvalue().encode("utf-8-sig")
