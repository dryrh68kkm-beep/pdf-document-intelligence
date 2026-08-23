"""Regression guard for a real stored-XSS bug found during an app audit:
product names/departments/filenames/etc. ultimately come from untrusted
PDF/OCR text or an imported master-catalog CSV, but were interpolated
directly into innerHTML across most of the frontend's data tables and
dialogs with no escaping at all - a master CSV row (or a cleverly-named
uploaded PDF) with a product name like "<img src=x onerror=...>" executed
in the browser. Live-verified fixed via headless Chromium against a real
running server (see PR description); this is the fast source-level guard
that keeps each fixed file wired to the shared escaper.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "app"

ESCAPE_MODULE = FRONTEND / "escape.js"

# Every file that renders untrusted product/document/master-catalog data
# into innerHTML must import the shared escaper. This doesn't prove every
# interpolation site uses it (that's what the live Playwright check in the
# PR verified) - it's a cheap tripwire against the import itself being
# dropped in a future edit.
FILES_MUST_IMPORT_ESCAPE = [
    FRONTEND / "main.js",
    FRONTEND / "views" / "dashboard.js",
    FRONTEND / "views" / "products.js",
    FRONTEND / "views" / "review.js",
    FRONTEND / "views" / "productMaster.js",
    FRONTEND / "views" / "documents.js",
    FRONTEND / "views" / "departments.js",
    FRONTEND / "views" / "divisionDetail.js",
    FRONTEND / "views" / "nonproduct.js",
    FRONTEND / "components" / "detailPanel.js",
]


def test_escape_module_exists_and_escapes_the_dangerous_characters():
    source = ESCAPE_MODULE.read_text(encoding="utf-8")
    assert "export function escapeHtml" in source
    for char in ("&", "<", ">", '"', "'"):
        assert char in source


def test_every_view_rendering_untrusted_data_imports_the_shared_escaper():
    for path in FILES_MUST_IMPORT_ESCAPE:
        source = path.read_text(encoding="utf-8")
        assert "escape.js" in source, f"{path.relative_to(ROOT)} does not import the shared escapeHtml helper"


def test_dashboard_no_longer_defines_its_own_duplicate_escaper():
    source = (FRONTEND / "views" / "dashboard.js").read_text(encoding="utf-8")
    assert "function escapeHtml" not in source
