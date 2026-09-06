"""Documents view: a bulk Reprocess action next to the existing per-row
Reprocess button - a user with many documents flagged for review had no
way to resubmit all of them without clicking Reprocess one row at a time.

Follow-up user request: the bulk action originally targeted every document
matching the current filter (minus ones already mid-processing), including
documents that were already fine - reprocessing a healthy document wastes
an OCR run for nothing. Restricted to isProblemDocument(doc) (the same
HIGH_RISK/error definition the per-row warning styling already uses) so it
only resubmits documents that are actually stuck or have a real problem.

Second follow-up user report: that restriction left the button disabled
for this user's real document set - every visible document had pending
review items but none were HIGH_RISK/errored/status==="error", so the
target list came up empty. A change at that point broadened eligibility
to also include a document with unresolved review items
(qualityCounts.needReview > 0).

Third follow-up user report ("กดแล้ว reprocess ใหม่หมดทุกเอกสาร" - clicking
it reprocesses every document again): in this user's actual data, almost
every document has *some* pending review item, so that broadening made
the "restricted" button functionally equivalent to reprocessing
everything again - exactly what the original restriction was meant to
prevent. Reprocessing isn't even the right fix for a review item in the
first place (that needs a human correction, not another OCR pass over the
same PDF) - reverted back to isProblemDocument alone. The button staying
disabled when nothing genuinely needs reprocessing is correct, not a bug.

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

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ROOT / "frontend" / "app" / "views" / "documents.js"

NODE = shutil.which("node")


def _source() -> str:
    return DOCUMENTS.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace_start = source.index("{", start)
    depth = 0
    i = brace_start
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


def _is_problem_document(doc):
    fn = _extract_function(_source(), "isProblemDocument")
    script = f"""
{fn}
console.log(JSON.stringify(isProblemDocument({json.dumps(doc)})));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _is_reprocess_target(doc):
    source = _source()
    problem_fn = _extract_function(source, "isProblemDocument")
    target_fn = _extract_function(source, "isReprocessTarget")
    script = f"""
{problem_fn}
{target_fn}
console.log(JSON.stringify(isReprocessTarget({json.dumps(doc)})));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_healthy_complete_document_is_not_a_problem():
    assert _is_problem_document({"status": "complete", "qualityBand": "GOOD", "qualityCounts": {"errors": 0}}) is False


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_an_errored_document_is_a_problem():
    assert _is_problem_document({"status": "error", "qualityBand": None, "qualityCounts": None}) is True


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_high_risk_or_error_count_document_is_a_problem_even_if_status_is_complete():
    assert _is_problem_document({"status": "complete", "qualityBand": "HIGH_RISK", "qualityCounts": {"errors": 0}}) is True
    assert _is_problem_document({"status": "complete", "qualityBand": "GOOD", "qualityCounts": {"errors": 2}}) is True


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_document_still_processing_is_not_flagged_a_problem():
    # A document genuinely mid-processing (not stuck) must not be swept up
    # by the bulk Reprocess action just for being in that state.
    assert _is_problem_document({"status": "processing", "qualityBand": None, "qualityCounts": None}) is False


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_document_with_only_pending_review_items_is_not_a_reprocess_target():
    # Reverted user report: a document needing review but with no hard
    # error must NOT be swept up by bulk Reprocess - in real data almost
    # every document has some review item, so including these made the
    # "restricted" button reprocess everything again. Review items need a
    # human correction, not another OCR pass.
    doc = {"status": "complete", "qualityBand": "GOOD", "qualityCounts": {"errors": 0, "needReview": 27}}
    assert _is_problem_document(doc) is False
    assert _is_reprocess_target(doc) is False


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_genuinely_healthy_document_is_not_a_reprocess_target():
    doc = {"status": "complete", "qualityBand": "GOOD", "qualityCounts": {"errors": 0, "needReview": 0}}
    assert _is_reprocess_target(doc) is False


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_problem_document_is_still_a_reprocess_target():
    assert _is_reprocess_target({"status": "error", "qualityBand": None, "qualityCounts": None}) is True


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
    targets_start = source.index("const reprocessTargets =")
    targets_end = source.index(";", targets_start)
    assert 'doc.status !== "processing"' in source[targets_start:targets_end]


def test_reprocess_all_only_targets_stuck_or_problem_documents():
    """User request: bulk Reprocess must not resubmit every document
    matching the current filter, only the ones actually stuck/problematic
    (isReprocessTarget - HIGH_RISK quality, a validation error, or
    status==="error") - reprocessing an already-healthy document, or one
    that only needs a human review correction, wastes an OCR run for
    nothing."""
    source = _source()
    targets_start = source.index("const reprocessTargets =")
    targets_end = source.index(";", targets_start)
    assert "isReprocessTarget(doc)" in source[targets_start:targets_end]
    assert "reprocessTargets.length" in source


def test_reprocess_all_targets_the_filtered_list_not_only_the_current_page():
    """"All" must mean everything the current filter matched (`visible`),
    not just the 10 rows paginate() put on screen - otherwise a user who
    filtered down to e.g. only ผิดพลาด documents and clicked "Reprocess
    เอกสารที่ค้าง/มีปัญหา (12)" would silently only get the first page
    resubmitted."""
    source = _source()
    button_start = source.index('id="reprocessAllBtn"')
    button_line_end = source.index("\n", button_start)
    button_markup = source[button_start:button_line_end]
    assert "reprocessableCount" in button_markup
    targets_start = source.index("const reprocessTargets =")
    targets_end = source.index(";", targets_start)
    assert "visible.filter" in source[targets_start:targets_end]
    handler_start = source.index('#reprocessAllBtn")?.addEventListener("click"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "reprocessTargets" in handler_body


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
