"""Regression guard (Level 7): GET /api/export.xlsx used to leak a
temp .xlsx file into the OS temp directory on every call - FileResponse
doesn't delete the file it streams, and the endpoint never scheduled a
cleanup. Reproduced with 5 real calls before fixing (5 files leaked,
0 cleaned up).
"""
from __future__ import annotations

import glob
import tempfile

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.api.store import store
from tests.unit.db_helpers import make_result, make_row


def test_export_does_not_leak_temp_files():
    store.reset_for_tests()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    rows = [make_row(0, "BAKERY", "BC1", "ART1", "Product", 1.0, 2, 3)]
    result = make_result(doc["id"], "t.pdf", [("BAKERY", rows)])
    flat = prepare_flat_rows(doc["id"], result, store.repo)
    store.repo.complete_document_with_rows(doc["id"], 1, {"confidence": 0.9}, flat)

    before = set(glob.glob(tempfile.gettempdir() + "/*.xlsx"))
    client = TestClient(app)
    for _ in range(5):
        res = client.get("/api/export.xlsx")
        assert res.status_code == 200
    after = set(glob.glob(tempfile.gettempdir() + "/*.xlsx"))

    assert after - before == set(), f"export leaked temp files: {after - before}"
