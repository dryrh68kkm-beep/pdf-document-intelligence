"""Live report (browser Console): GET /api/state 500ing broke the entire
initial page load, not just one document - build_dashboard_state()
aggregates over every product row in the whole app in one pass with no
per-row isolation, and its _json_list() helper had the exact same
unguarded json.loads() bug independently fixed in divisions.py (PR #115/
#116/#119) and serialize.py (PR #120) - the fourth occurrence, which is
why a shared pdf_document_intelligence.api.json_safety.safe_json_loads()
now exists instead of a fifth copy-pasted fix.
"""
from __future__ import annotations

from pdf_document_intelligence.api.aggregate import build_dashboard_state
from pdf_document_intelligence.api.rows import persist_document_result
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository
from tests.unit.db_helpers import make_result, make_row


def _repo(tmp_path):
    return Repository(open_independent_connection(tmp_path / "app.db"))


def _seed(repo, tmp_path):
    repo.create_document("doc-1", sha256="a", filename="doc1.pdf", file_size=1)
    row = make_row(0, "BAKERY", "8850000000001", "ART1", "ขนมปัง A", 10.0, 2, 4, review=True, flags=["MISSING_AMOUNT"])
    repo.set_document_complete("doc-1", 1, {"confidence": 0.97, "statusDocument": "AUTO_APPROVED", "reconciled": True})
    persist_document_result("doc-1", make_result("doc-1", "doc1.pdf", [("BAKERY", [row])]), repo)


def test_corrupted_review_reasons_does_not_crash_the_whole_state(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    repo._conn.execute("UPDATE product_rows SET review_reasons = ? WHERE document_id = ?", ("{not valid json", "doc-1"))
    repo._conn.commit()

    state = build_dashboard_state(repo)

    # The row is skipped (its own data is corrupted), but the call itself
    # must not raise - every OTHER document's numbers stay intact.
    assert isinstance(state["reviewItems"], list)
    assert isinstance(state["grandTotals"], dict)


def test_review_reasons_not_a_list_is_tolerated():
    from pdf_document_intelligence.api.aggregate import _json_list

    assert _json_list('"just a string"') == []
    assert _json_list("42") == []
    assert _json_list(None) == []
    assert _json_list("") == []


def test_review_priority_tolerates_unhashable_reason_items():
    from pdf_document_intelligence.api.aggregate import _review_priority

    row = {"review_reasons": '[{"nested": "object"}, "AMOUNT_MISMATCH"]'}
    # Must not raise TypeError (unhashable dict used as a dict key) and
    # must still find the one recognizable, ranked reason.
    assert _review_priority(row) == 1


def test_non_product_reasons_corrupted_json_does_not_crash_the_whole_state(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, tmp_path)
    repo._conn.execute(
        "UPDATE product_rows SET suspected_non_product = 1, non_product_reasons = ? WHERE document_id = ?",
        ("{not valid json", "doc-1"),
    )
    repo._conn.commit()

    state = build_dashboard_state(repo)

    assert isinstance(state["nonProductItems"], list)


def test_an_unforeseen_department_summary_failure_is_skipped_not_crashed(tmp_path, monkeypatch):
    """Structural fix (matches divisions.py's equivalent test): whatever
    about a department's summary turns out to fail - not one of the
    shapes already fixed above - must skip only that department, never
    the whole dashboard state. The row itself is unaffected (it's
    processed in an earlier, separate loop), only its department's
    aggregated summary is dropped."""
    import pdf_document_intelligence.api.aggregate as aggregate_module

    repo = _repo(tmp_path)
    _seed(repo, tmp_path)

    real_major_department_for = aggregate_module.major_department_for

    def _flaky(name):
        raise RuntimeError("simulated unforeseen corruption")

    monkeypatch.setattr(aggregate_module, "major_department_for", _flaky)
    state = build_dashboard_state(repo)
    monkeypatch.setattr(aggregate_module, "major_department_for", real_major_department_for)

    assert state["rowCount"] == 1
    assert state["departments"] == []
