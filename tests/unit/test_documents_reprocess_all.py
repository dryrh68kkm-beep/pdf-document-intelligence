"""Documents view: a "Reprocess ทั้งหมด" bulk action next to the existing
per-row Reprocess button - a user with many documents flagged for review
had no way to resubmit all of them without clicking Reprocess one row at a
time.

documents.js is a DOM-driving view module with no pure function to execute
outside a real browser, matching this project's established pattern for
this bug class (see test_documents_view_pdf.py) - these are source-level
regression guards. Live-verified in a real browser during development:
clicking "Reprocess ทั้งหมด" on 3 documents (1 already complete, 1 real
BPDC packing list, 1 corrupted leftover PDF) showed a confirm dialog
naming the count, then submitted all three - two began reprocessing
normally and the corrupted one surfaced its real PDF_CORRUPTED error via
the document's own status, exactly as a single Reprocess click on it
would.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ROOT / "frontend" / "app" / "views" / "documents.js"


def _source() -> str:
    return DOCUMENTS.read_text(encoding="utf-8")


def test_reprocess_all_button_is_wired():
    source = _source()
    assert 'id="reprocessAllBtn"' in source
    assert '#reprocessAllBtn' in source


def test_reprocess_all_excludes_documents_already_processing():
    """A document already mid-processing can't be resubmitted - the backend
    (POST /api/documents/{id}/reprocess) 423s a second submission via
    mark_reprocessing(), matching the guard the per-row button already
    applies (`doc.status !== "processing"`)."""
    source = _source()
    handler_start = source.index('#reprocessAllBtn")?.addEventListener("click"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert 'doc.status !== "processing"' in handler_body


def test_reprocess_all_targets_the_filtered_list_not_only_the_current_page():
    """"All" must mean everything the current filter matched (`visible`),
    not just the 10 rows paginate() put on screen - otherwise a user who
    filtered down to e.g. only ผิดพลาด documents and clicked "Reprocess
    ทั้งหมด (12)" would silently only get the first page resubmitted."""
    source = _source()
    button_start = source.index('id="reprocessAllBtn"')
    button_line_end = source.index("\n", button_start)
    button_markup = source[button_start:button_line_end]
    assert "reprocessableCount" in button_markup
    assert "reprocessableCount = visible.filter" in source
    handler_start = source.index('#reprocessAllBtn")?.addEventListener("click"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "visible.filter" in handler_body


def test_reprocess_all_confirms_before_submitting():
    source = _source()
    handler_start = source.index('#reprocessAllBtn")?.addEventListener("click"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "confirmDialog" in handler_body
    assert "show-confirm" in handler_body


def test_reprocess_all_uses_allsettled_so_one_failure_does_not_abort_the_rest():
    """A single document rejecting its reprocess call (e.g. a corrupted PDF,
    or a race against a document that started processing on its own) must
    not stop the other targets from being submitted - Promise.all would
    reject and abandon whatever hadn't started yet."""
    source = _source()
    handler_start = source.index('#reprocessAllBtn")?.addEventListener("click"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "Promise.allSettled" in handler_body
    assert "api.reprocessDocument(doc.id)" in handler_body


def test_reprocess_all_refreshes_once_and_surfaces_failures():
    source = _source()
    handler_start = source.index('#reprocessAllBtn")?.addEventListener("click"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "store.refreshAll()" in handler_body
    assert "errorDialog" in handler_body
    assert "show-error" in handler_body
