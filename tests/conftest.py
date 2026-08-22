"""Test-session-wide isolation and synthetic operational metadata.

Tests must never depend on company PDFs, expected dumps, or a production
master catalog. Everything needed by the suite is generated into a temporary
directory before application modules are imported.
"""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="pdi_test_data_"))
os.environ["PDF_INTELLIGENCE_DATA_DIR"] = str(_TEST_DATA_DIR)

# Minimal test-only hierarchy. It contains no product/barcode/price/master
# records and exists only in the runner temp directory. These pairings are
# synthetic test contracts and must not be treated as production hierarchy.
_TEST_CATALOG = _TEST_DATA_DIR / "synthetic_hierarchy.csv"
_rows = [
    ("HBA", "04 DRY FOOD"),
    ("BEVERAGE", "04 DRY FOOD"),
    ("SWEETED GROCE.1", "04 DRY FOOD"),
    ("SWEETED GROCE.2", "04 DRY FOOD"),
    ("SWEETED GROCE.2_SME", "04 DRY FOOD"),
    ("SALTED GROCERY", "04 DRY FOOD"),
    ("SALTED GROCERY_SME", "04 DRY FOOD"),
    ("FACE & COSMETICS", "04 DRY FOOD"),
    ("HOUSEWARE", "02 HOME LINE"),
    ("STATIONERY & EDUTAINMENT", "02 HOME LINE"),
    ("SYNTHETIC SOFTLINE", "03 SOFT LINE"),
    ("SMALL APPLIANCE", "01 HARD LINE"),
    ("BUTCHERY", "05 FRESH FOOD"),
    ("PRESCRIPTION", "06 PHARMACY"),
]
with _TEST_CATALOG.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["DEPARTMENT_NAME", "DIVISION_NAME"])
    writer.writeheader()
    for department, division in _rows:
        writer.writerow({"DEPARTMENT_NAME": department, "DIVISION_NAME": division})
os.environ["PDF_INTELLIGENCE_MASTER_CATALOG"] = str(_TEST_CATALOG)
