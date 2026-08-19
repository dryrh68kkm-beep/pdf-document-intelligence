"""SQLite persistence: restart survival, duplicate detection after
restart, batch insert, corrections + audit trail, undo, recalculation,
department move, local product master (spec P0/P1/P2/P3, items 4-19)."""
from __future__ import annotations

import hashlib

import pytest

from pdf_document_intelligence.api.aggregate import build_dashboard_state
from pdf_document_intelligence.api.review import apply_correction, confirm_review_row
from pdf_document_intelligence.api.rows import persist_document_result
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository, new_id
from tests.unit.db_helpers import make_result, make_row


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "app.db"


def _repo_at(db_path):
    return Repository(open_independent_connection(db_path))


def _seed_document(repo: Repository, doc_id="doc-1"):
    repo.create_document(doc_id, sha256="abc123", filename="test.pdf", file_size=100)
    rows = [
        make_row(0, "BAKERY", "8850000000001", "ART1", "ขนมปัง A", 10.0, 5, 5),
        make_row(1, "BAKERY", "8850000000002", "ART2", "ขนมปัง B", 8.0, 4, 4, review=True, flags=["OCR_LOW_CONFIDENCE"]),
        make_row(2, "UNKNOWN", "8850000000003", "ART3", "สินค้า C", 3.0, 2, 2),
    ]
    result = make_result(doc_id, "test.pdf", [("BAKERY", rows[:2]), ("UNKNOWN", rows[2:])])
    repo.set_document_complete(doc_id, 1, {"confidence": 0.97, "statusDocument": "AUTO_APPROVED", "reconciled": True})
    persist_document_result(doc_id, result, repo)
    return result


# --- Restart persistence (items 4, 35) ---

def test_data_survives_restart(db_path):
    repo1 = _repo_at(db_path)
    _seed_document(repo1)

    repo2 = _repo_at(db_path)  # simulates a fresh process reopening the same file
    docs = repo2.list_documents()
    assert len(docs) == 1
    rows = repo2.list_product_rows()
    assert len(rows) == 3
    state = build_dashboard_state(repo2)
    assert state["documentCount"] == 1
    assert state["rowCount"] == 3
    assert state["departmentCount"] == 2


# --- Duplicate detection after restart (items 5, 36) ---

def test_duplicate_detection_survives_restart(db_path):
    repo1 = _repo_at(db_path)
    sha = hashlib.sha256(b"same pdf bytes").hexdigest()
    repo1.create_document("doc-1", sha256=sha, filename="a.pdf", file_size=10)

    repo2 = _repo_at(db_path)
    assert repo2.find_document_by_sha256(sha) is not None
    assert repo2.find_document_by_sha256("not-a-real-hash") is None


# --- Batch insert / reprocess preserves ids + soft-deletes stale rows ---

def test_reprocess_matches_existing_rows_by_barcode(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    rows_before = {r["barcode"]: r["id"] for r in repo.list_product_rows()}

    # Reprocess with the same barcodes but a slightly different weight.
    new_rows = [
        make_row(0, "BAKERY", "8850000000001", "ART1", "ขนมปัง A", 11.0, 5, 5),
        make_row(1, "BAKERY", "8850000000002", "ART2", "ขนมปัง B", 8.0, 4, 4),
    ]
    result = make_result("doc-1", "test.pdf", [("BAKERY", new_rows)])
    outcome = persist_document_result("doc-1", result, repo)

    rows_after = {r["barcode"]: r["id"] for r in repo.list_product_rows()}
    assert rows_after["8850000000001"] == rows_before["8850000000001"]  # same id, not a new row
    assert outcome["soft_deleted"] == 1  # the UNKNOWN/ART3 row from before is gone now
    remaining_barcodes = {r["barcode"] for r in repo.list_product_rows()}
    assert "8850000000003" not in remaining_barcodes


def test_reprocess_does_not_silently_override_a_corrected_field(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = next(r for r in repo.list_product_rows() if r["barcode"] == "8850000000001")
    apply_correction(repo, row["id"], "weight_qty", 99.0, reason="ตรวจจาก PDF ต้นฉบับ")

    new_rows = [make_row(0, "BAKERY", "8850000000001", "ART1", "ขนมปัง A", 5.0, 5, 5)]
    result = make_result("doc-1", "test.pdf", [("BAKERY", new_rows)])
    persist_document_result("doc-1", result, repo)

    reloaded = repo.get_product_row(row["id"])
    assert reloaded["weight_qty"] == 99.0  # correction preserved, not overwritten by reprocess


# --- Editable review + audit trail (items 6-10) ---

def test_correction_is_saved_and_recorded_in_audit_history(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = repo.list_product_rows()[0]

    apply_correction(repo, row["id"], "sku_qty", 10, reason="ยืนยันจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    assert reloaded["sku_qty"] == 10.0
    assert reloaded["resolution_status"] == "CORRECTED"

    history = repo.list_corrections(row["id"])
    assert len(history) == 1
    assert history[0]["field_name"] == "sku_qty"
    assert history[0]["new_value"] == "10.0"
    assert history[0]["source"] == "LOCAL_USER"


def test_barcode_correction_requires_a_reason(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = repo.list_product_rows()[0]
    with pytest.raises(Exception):
        apply_correction(repo, row["id"], "barcode", "8850000009999", reason=None)


def test_negative_quantity_is_rejected(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = repo.list_product_rows()[0]
    with pytest.raises(Exception):
        apply_correction(repo, row["id"], "sku_qty", -5, reason="typo")


# --- Undo (item 11): creates a new record, never deletes history ---

def test_undo_creates_new_record_and_keeps_history(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = repo.list_product_rows()[0]
    result = apply_correction(repo, row["id"], "sku_qty", 10, reason="test")
    correction_id = result["correction_id"]

    repo.undo_correction(correction_id)

    reloaded = repo.get_product_row(row["id"])
    assert reloaded["sku_qty"] == row["sku_qty"]  # back to original
    history = repo.list_corrections(row["id"])
    assert len(history) == 2  # original correction + undo, neither deleted


# --- Recalculation engine (items 12, 14) ---

def test_dashboard_recalculates_after_correction(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    before = build_dashboard_state(repo)
    row = next(r for r in repo.list_product_rows() if r["department"] == "BAKERY")

    apply_correction(repo, row["id"], "sku_qty", row["sku_qty"] + 100, reason="test")

    after = build_dashboard_state(repo)
    bakery_before = next(d for d in before["departments"] if d["name"] == "BAKERY")
    bakery_after = next(d for d in after["departments"] if d["name"] == "BAKERY")
    assert bakery_after["totals"]["sku_qty"] == bakery_before["totals"]["sku_qty"] + 100
    assert after["grandTotals"]["sku_qty"] == before["grandTotals"]["sku_qty"] + 100


def test_department_move_recalculates_both_departments(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = next(r for r in repo.list_product_rows() if r["department"] == "UNKNOWN")
    sku_qty = row["sku_qty"]

    apply_correction(repo, row["id"], "department", "BAKERY", reason="ยืนยันแล้ว")

    state = build_dashboard_state(repo)
    dept_names = {d["name"] for d in state["departments"]}
    assert "UNKNOWN" not in dept_names or next(d for d in state["departments"] if d["name"] == "UNKNOWN")["rowCount"] == 0
    bakery = next(d for d in state["departments"] if d["name"] == "BAKERY")
    assert bakery["rowCount"] == 3  # 2 original + the moved row


# --- Amount validation (item 13) ---

def test_amount_mismatch_flag_appears_and_clears(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = repo.list_product_rows()[0]

    apply_correction(repo, row["id"], "unit_price", 10.0, reason="test")
    apply_correction(repo, row["id"], "amount", 999.0, reason="test")
    mismatched = repo.get_product_row(row["id"])
    import json
    assert "AMOUNT_MISMATCH" in json.loads(mismatched["review_reasons"])

    apply_correction(repo, row["id"], "amount", mismatched["sku_qty"] * 10.0, reason="fixed")
    fixed = repo.get_product_row(row["id"])
    assert "AMOUNT_MISMATCH" not in json.loads(fixed["review_reasons"])


# --- Bulk confirm safety (item 21) ---

def test_bulk_confirm_refuses_unresolved_amount_mismatch(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = repo.list_product_rows()[0]
    apply_correction(repo, row["id"], "unit_price", 10.0, reason="test")
    apply_correction(repo, row["id"], "amount", 999.0, reason="test")
    with pytest.raises(Exception):
        confirm_review_row(repo, row["id"])


def test_bulk_confirm_clears_a_safe_review_item(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    row = next(r for r in repo.list_product_rows() if r["review_required"])
    confirm_review_row(repo, row["id"])
    assert repo.get_product_row(row["id"])["review_required"] == 0


# --- Local product master (items 16-19) ---

def test_local_master_add_and_duplicate_protection(db_path):
    repo = _repo_at(db_path)
    first = repo.add_local_master("8850000009999", "สินค้าทดสอบ", "BAKERY", "PCS", "ART9", None)
    assert first["created"] is True
    second = repo.add_local_master("8850000009999", "ชื่ออื่น", "BAKERY", "PCS", "ART9", None)
    assert second["created"] is False  # no duplicate row created
    assert repo.count_local_master() == 1


def test_local_master_resolves_future_upload_without_ocr(db_path):
    repo = _repo_at(db_path)
    repo.add_local_master("8850000000003", "สินค้ายืนยันแล้ว", "BAKERY", "PCS", "ART3", None)

    row = make_row(0, "BAKERY", "8850000000003", "ART3", "ชื่อจาก OCR เก่า", 3.0, 2, 2)
    result = make_result("doc-2", "second.pdf", [("BAKERY", [row])])
    repo.create_document("doc-2", sha256="xyz", filename="second.pdf", file_size=10)
    repo.set_document_complete("doc-2", 1, {"confidence": 0.9})
    persist_document_result("doc-2", result, repo)

    stored = repo.list_product_rows(document_id="doc-2")[0]
    assert stored["resolved_product_name"] == "สินค้ายืนยันแล้ว"
    assert stored["resolution_status"] == "LOCAL_MASTER"


def test_master_coverage_kpi_reports_real_counts(db_path):
    repo = _repo_at(db_path)
    _seed_document(repo)
    state = build_dashboard_state(repo)
    total_pct = sum(item["percent"] for item in state["masterCoverage"])
    assert 99.0 <= total_pct <= 101.0  # rounding tolerance, not fabricated
