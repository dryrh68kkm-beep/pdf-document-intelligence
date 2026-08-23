from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.api.store import store
from tests.unit.db_helpers import make_result, make_row


def _complete(filename: str, document_date: str, barcode: str, article: str, amount: float):
    doc = store.create(filename, f"%PDF-1.4 {filename}".encode())
    tables = [("HBA", [make_row(0, "HBA", barcode, article, "Product", 1.0, 1, 1)])]
    result = make_result(doc["id"], filename, tables)
    flat = prepare_flat_rows(doc["id"], result, store.repo)
    store.repo.complete_document_with_rows(
        doc["id"],
        1,
        {"confidence": 0.9, "documentDate": document_date},
        flat,
    )
    row_id = store.repo.list_product_rows(document_id=doc["id"])[0]["id"]
    client = TestClient(app)
    response = client.patch(
        f"/api/products/{row_id}",
        json={"field": "amount", "value": amount, "reason": "synthetic test value"},
    )
    assert response.status_code == 200
    return doc


def test_dashboard_overview_aggregates_documents_in_one_endpoint():
    store.reset_for_tests()
    _complete("one.pdf", "2026-08-01", "BC1", "ART1", 10.10)
    _complete("two.pdf", "2026-08-03", "BC2", "ART2", 20.20)

    client = TestClient(app)
    response = client.get("/api/analytics/dashboard-overview")
    assert response.status_code == 200
    body = response.json()

    assert body["totals"] == {"rowCount": 2, "amount": 30.3, "documentCount": 2}
    assert len(body["divisions"]) == 6
    division_04 = next(item for item in body["divisions"] if item["divisionCode"] == "04")
    assert division_04["rowCount"] == 2
    assert division_04["amount"] == 30.3
    assert division_04["documentCount"] == 2
    assert body["amountAvailable"] is True


def test_dashboard_overview_filters_by_document_date_and_division():
    store.reset_for_tests()
    _complete("one.pdf", "2026-08-01", "BC1", "ART1", 10.0)
    _complete("two.pdf", "2026-08-03", "BC2", "ART2", 20.0)

    client = TestClient(app)
    date_body = client.get(
        "/api/analytics/dashboard-overview?date_from=2026-08-02&date_to=2026-08-31"
    ).json()
    assert date_body["totals"] == {"rowCount": 1, "amount": 20.0, "documentCount": 1}

    division_body = client.get("/api/analytics/dashboard-overview?division=04").json()
    assert division_body["selectedDivision"] == "04"
    assert division_body["totals"] == {"rowCount": 2, "amount": 30.0, "documentCount": 2}


def test_dashboard_overview_rejects_invalid_filters():
    store.reset_for_tests()
    client = TestClient(app)
    assert client.get(
        "/api/analytics/dashboard-overview?date_from=2026-08-31&date_to=2026-08-01"
    ).status_code == 400
    assert client.get("/api/analytics/dashboard-overview?division=99").status_code == 404
