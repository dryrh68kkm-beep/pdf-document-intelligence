"""Products view: show which document date each product row came in on
(user request: "เพิ่มข้อมูลสินค้าเข้าวันที่เท่าไร่" - add info on what date the
product was entered).

state.js already treats a document's documentDate as the one canonical date
field everything else (Dashboard/Products/Documents date-range scoping) is
built on (see inDocumentDateRange() and the date-range-consistency fix in
_computeDashboardOverview()) - product_row_json() itself carries no date, so
_doRefreshAll() now joins each product row onto its own document's
documentDate once per refresh (not per-render, matching the existing
_search-index precedent) rather than have every view re-join documents and
products itself.

fmtDate() in products.js is a small pure function - executed directly via
Node for real behavioral coverage. The join itself lives inline in
_doRefreshAll() (a network-driving method, not something to execute
outside a browser) and the row-count/date-scoping join precedent it follows
is already covered behaviorally elsewhere - this file checks its shape at
the source level, matching this project's established pattern for that
class of coverage (see test_products_row_action.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "frontend" / "app" / "state.js"
PRODUCTS = ROOT / "frontend" / "app" / "views" / "products.js"

NODE = shutil.which("node")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    paren_start = source.index("(", start)
    paren_depth = 0
    i = paren_start
    while True:
        if source[i] == "(":
            paren_depth += 1
        elif source[i] == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        i += 1
    brace_start = source.index("{", i)
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


def _run_fmt_date(value):
    source = PRODUCTS.read_text(encoding="utf-8")
    fn_source = _extract_function(source, "fmtDate")
    script = f"""
{fn_source}
console.log(JSON.stringify(fmtDate({json.dumps(value)})));
"""
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_fmt_date_renders_a_real_document_date():
    result = _run_fmt_date("2026-08-15")
    assert "2026" not in result or "2569" in result  # Buddhist-era year, th-TH locale
    assert result != "—"


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_fmt_date_falls_back_to_a_dash_for_a_missing_date():
    """A document with no labelled transaction date (extract_document_date()
    returns None) must not crash the column or show "Invalid Date" - the
    dash matches the fallback fmt() already uses for every other empty
    field on this table."""
    assert _run_fmt_date(None) == "—"
    assert _run_fmt_date("") == "—"


def test_products_table_has_a_document_date_column():
    source = PRODUCTS.read_text(encoding="utf-8")
    assert '"วันที่เอกสาร"' in source
    assert "r.documentDate" in source


def test_state_joins_each_product_row_onto_its_own_document_date():
    """Regression guard: product_row_json() (backend) carries no date field
    of its own - _doRefreshAll() must join it from `documents` once per
    refresh rather than a view silently rendering undefined/blank forever."""
    source = STATE.read_text(encoding="utf-8")
    refresh_start = source.index("async _doRefreshAll()")
    refresh_end = source.index("\n  }\n", refresh_start)
    body = source[refresh_start:refresh_end]
    assert "documentDateById" in body
    assert "documents.map((doc) => [doc.id, doc.documentDate])" in body
    assert "documentDate: documentDateById.get(p.docId)" in body
