"""User report: the Dashboard's "ข้อมูลสรุปไม่สมบูรณ์" banner (see PR #88)
showed one document out of several failing to load its Division summary,
even though the document itself was status "พร้อมใช้งาน" (complete) - no
error/processing state visible anywhere in the UI.

build_division_summary() previously had two unguarded spots that turn one
unusual row/document into an unhandled exception - a 500 from
GET /api/analytics/documents/{id}/divisions, which is exactly what the
frontend's ThaiOcrCrossValidator-era banner surfaces as "failed to fetch
this document's summary":

1. `buckets[code]` (a plain dict subscript) where `code` comes from
   division_for_department() - built from a *different*
   lru_cache(maxsize=1) reader over the same on-disk master snapshot than
   the one `buckets` itself is built from. Both are normally kept in sync
   by _clear_catalog_caches() clearing all of them together on a Product
   Master reimport, but that's an operational invariant, not something
   this function can prove holds - a code present in one and not the
   other must fold into "unmapped", never crash the whole document.
2. `_reconciliation()`'s bare `json.loads(doc["meta_json"])` and
   `i["severity"]` - a corrupted/truncated meta_json or a validation-issue
   dict missing "severity" must not 500 a field this function doesn't
   even need for the Division rollup itself.
"""
from __future__ import annotations

from unittest.mock import patch

from pdf_document_intelligence.api.divisions import build_division_summary
from pdf_document_intelligence.api.rows import persist_document_result
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository
from tests.unit.db_helpers import make_result, make_row


def _repo(tmp_path):
    return Repository(open_independent_connection(tmp_path / "app.db"))


def _seed(repo, tmp_path):
    repo.create_document("doc-1", sha256="a", filename="doc1.pdf", file_size=1)
    row = make_row(0, "BAKERY", "8850000000001", "ART1", "ขนมปัง A", 10.0, 2, 4)
    repo.set_document_complete("doc-1", 1, {"confidence": 0.97, "statusDocument": "AUTO_APPROVED", "reconciled": True})
    persist_document_result("doc-1", make_result("doc-1", "doc1.pdf", [("BAKERY", [row])]), repo)


def test_a_division_code_missing_from_buckets_does_not_crash_the_summary(tmp_path):
    """Simulates the exact skew build_division_summary() must survive:
    division_for_department() returns a code that isn't a key in the
    buckets dict built from get_default_divisions()."""
    repo = _repo(tmp_path)
    _seed(repo, tmp_path)

    with patch("pdf_document_intelligence.api.divisions.division_for_department", return_value=("99", "GHOST DIVISION")):
        summary = build_division_summary(repo, "doc-1")

    assert summary["documentTotals"]["rowCount"] == 1
    assert summary["dataQuality"]["unmappedRowCount"] == 1
    assert "BAKERY" in summary["dataQuality"]["unmappedDepartments"]


def test_corrupted_meta_json_does_not_crash_the_summary(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    repo._conn.execute("UPDATE documents SET meta_json = ? WHERE id = ?", ("{not valid json", "doc-1"))
    repo._conn.commit()

    summary = build_division_summary(repo, "doc-1")

    assert summary["reconciliation"] == {"status": None, "errors": 0}
    assert summary["documentTotals"]["rowCount"] == 1


def test_non_finite_amount_does_not_crash_the_summary(tmp_path):
    """Live report (browser Console): GET .../divisions returning 500 for
    specific documents with no visible cause elsewhere in the UI.
    Reproduces the exact failure - Decimal('Infinity').quantize(...)
    raises decimal.InvalidOperation, which _decimal() must now prevent
    from ever reaching a sum in the first place (see its own docstring)."""
    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    repo._conn.execute(
        "UPDATE product_rows SET amount = ? WHERE document_id = ?", (float("inf"), "doc-1")
    )
    repo._conn.commit()

    summary = build_division_summary(repo, "doc-1")

    assert summary["documentTotals"]["rowCount"] == 1
    # The non-finite amount is treated as unusable, not summed as "inf baht" -
    # same as any other row with no amount at all.
    assert summary["documentTotals"]["amount"] == 0.0


def test_meta_json_valid_but_not_an_object_does_not_crash_the_summary(tmp_path):
    """Live report (Console, diagnosticId ERR-F24754DF): meta_json = "null"
    is syntactically valid JSON (json.loads() returns None, no exception),
    but meta.get(...) on a non-dict raises AttributeError - a distinct
    failure from the malformed-JSON-text case above, since AttributeError
    isn't a TypeError/ValueError the existing except clause would catch."""
    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    repo._conn.execute("UPDATE documents SET meta_json = ? WHERE id = ?", ("null", "doc-1"))
    repo._conn.commit()

    summary = build_division_summary(repo, "doc-1")

    assert summary["reconciliation"] == {"status": None, "errors": 0}
    assert summary["documentTotals"]["rowCount"] == 1


def test_validation_issues_not_a_list_does_not_crash_the_summary(tmp_path):
    """Live report (Console, several new diagnosticIds): a fourth
    corrupted-meta_json shape - "validationIssues" is present and meta is a
    dict (so the isinstance guard above doesn't catch it), but its value
    isn't a list of objects. Iterating a string yields characters, and
    i.get(...) on a str raises AttributeError - a case the earlier
    isinstance(meta, dict) fix didn't cover."""
    import json

    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    meta = json.dumps({"reconciled": True, "validationIssues": "not-a-list"})
    repo._conn.execute("UPDATE documents SET meta_json = ? WHERE id = ?", (meta, "doc-1"))
    repo._conn.commit()

    summary = build_division_summary(repo, "doc-1")

    assert summary["reconciliation"] == {"status": None, "errors": 0}
    assert summary["documentTotals"]["rowCount"] == 1


def test_validation_issue_missing_severity_key_does_not_crash_the_summary(tmp_path):
    import json

    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    meta = json.dumps({"reconciled": True, "validationIssues": [{"message": "no severity field here"}]})
    repo._conn.execute("UPDATE documents SET meta_json = ? WHERE id = ?", (meta, "doc-1"))
    repo._conn.commit()

    summary = build_division_summary(repo, "doc-1")

    assert summary["reconciliation"]["status"] == "PASSED"
    assert summary["reconciliation"]["errors"] == 0
