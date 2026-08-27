"""PR18 (Documents UX): the Documents page had no way at all to view the
original PDF - it was only reachable indirectly, per product row, via the
detail panel's own "ดูจากเอกสารต้นฉบับ" link, which needs a completed,
reconciled row to exist first. A document mid-processing, or one that
errored out with zero rows, had no path to its own source file anywhere
in the UI even though the file has been on disk since the moment it was
uploaded (api/app.py moves it into place before any processing job is
even submitted - PR5).

Extracted the existing PDF-modal code out of detailPanel.js (which had it
working and tested since the Division-detail work) into pdfViewer.js so
Documents didn't duplicate it - matching the pattern PR17 already
established for confirmMarkResolved.

These files have no DOM-free pure function to execute directly, matching
the project's established pattern for this bug class - source-level
regression guards. Live-verified in a real browser during development:
clicking the new "ดู PDF ต้นฉบับ" icon on a Documents row opens the modal
with the real PDF loaded, for a document with zero product rows (which
the old per-row-only path could never have reached).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF_VIEWER = ROOT / "frontend" / "app" / "pdfViewer.js"
DOCUMENTS = ROOT / "frontend" / "app" / "views" / "documents.js"
DETAIL_PANEL = ROOT / "frontend" / "app" / "components" / "detailPanel.js"


def test_pdf_viewer_module_uses_the_real_pdf_url():
    source = PDF_VIEWER.read_text(encoding="utf-8")
    assert "api.pdfUrl(docId)" in source
    assert 'from "./api.js"' in source


def test_documents_view_wires_a_real_view_pdf_action():
    source = DOCUMENTS.read_text(encoding="utf-8")
    assert 'data-action="view-pdf"' in source
    assert "openPdfModal(doc.id" in source
    assert 'from "../pdfViewer.js"' in source


def test_detail_panel_reuses_the_shared_pdf_viewer_not_a_duplicate():
    """Regression guard: detailPanel.js used to build its own inline modal
    markup (~15 duplicated lines) - it must now call the shared helper
    instead of a second copy existing alongside documents.js's."""
    source = DETAIL_PANEL.read_text(encoding="utf-8")
    assert "openPdfModal(product.docId" in source
    assert 'from "../pdfViewer.js"' in source
    # The old inline modal-building code must be gone from this file.
    assert "modal-pdf-head" not in source
