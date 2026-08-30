"""Regression test for the Dashboard/Products/Documents date-range mismatch.

Uploads a mix of Big C and BPDC synthetic documents through the real API and
verifies that:
  - /api/documents completed-document count for a date range,
  - /api/products row count (excluding suspected-non-product rows) for the
    same range, and
  - the sum of per-document /api/analytics/documents/{id}/divisions
    documentTotals for that range
are all mutually consistent - the same invariant the Dashboard's
_computeDashboardOverview()/buildDashboardOverview() must now preserve on the
frontend (see tests/unit/test_dashboard_reconciliation_warning.py for the
pure-function-level coverage of that fix).
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from tests.synthetic_documents import make_bigc_pdf, make_bpdc_pdf


def _wait_complete(client: TestClient, doc_id: str, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in ("complete", "error"):
            return doc
        time.sleep(1)
    raise TimeoutError("document did not finish processing in time")


def _upload(client: TestClient, path, filename: str) -> dict:
    with path.open("rb") as f:
        res = client.post("/api/documents", files={"file": (filename, f, "application/pdf")})
    assert res.status_code == 200
    doc_id = res.json()["id"]
    return _wait_complete(client, doc_id)


def test_mixed_bigc_bpdc_documents_are_consistent_across_views(tmp_path):
    store.reset_for_tests()
    client = TestClient(app)

    bigc_a = make_bigc_pdf(tmp_path / "bigc-a.pdf")
    bigc_b = make_bigc_pdf(tmp_path / "bigc-b.pdf")
    bpdc_a = make_bpdc_pdf(tmp_path / "bpdc-a.pdf")

    docs = [
        _upload(client, bigc_a, "bigc-a.pdf"),
        _upload(client, bigc_b, "bigc-b.pdf"),
        _upload(client, bpdc_a, "bpdc-a.pdf"),
    ]
    assert all(doc["status"] == "complete" for doc in docs), docs

    all_documents = client.get("/api/documents").json()
    completed = [d for d in all_documents if d["status"] == "complete" and d["id"] in {doc["id"] for doc in docs}]
    assert len(completed) == 3

    dates = [d["documentDate"] for d in completed if d["documentDate"]]
    assert dates, "synthetic documents must extract a documentDate for a range query to be meaningful"
    date_from, date_to = min(dates), max(dates)

    in_range_ids = {
        d["id"] for d in completed
        if d["documentDate"] and date_from <= d["documentDate"] <= date_to
    }
    document_count = len(in_range_ids)
    assert document_count == 3

    all_products = client.get("/api/products").json()
    row_count = sum(
        1 for p in all_products
        if not p["suspectedNonProduct"] and p["docId"] in in_range_ids
    )
    assert row_count > 0

    division_row_total = 0
    incomplete_count = 0
    for doc_id in in_range_ids:
        res = client.get(f"/api/analytics/documents/{doc_id}/divisions")
        if res.status_code != 200:
            incomplete_count += 1
            continue
        division_row_total += res.json()["documentTotals"]["rowCount"]

    # No document's Division summary should fail for a normally-uploaded,
    # completed document - this is the "must comprehensively include every
    # document" requirement.
    assert incomplete_count == 0

    # rowCount from /api/products (what Products.js shows) must equal the
    # sum of rowCount across each document's Division summary (what feeds
    # the Dashboard's Division breakdown) for the same date range - the two
    # independent sources the fix requires to stay in lockstep.
    assert row_count == division_row_total
