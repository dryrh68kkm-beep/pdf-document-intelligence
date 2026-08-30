"""PR10 (Data Accuracy Gate): the Dashboard's headline totals are summed
across every "complete" document regardless of whether that document's own
declared Total matched its extracted line items (`reconciled`). Excluding
unreconciled documents outright would make numbers silently vanish - the
user's explicit choice was to keep including them in the totals but make
their presence visible, so a document whose numbers may be wrong doesn't
look exactly as trustworthy as one that passed reconciliation.

frontend/app/state.js's buildDashboardOverview() is a pure function (no DOM,
no imports) - executed directly via Node for a real behavioral test rather
than a source-text check, with a skip guard so this never breaks CI on a
runner without Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "frontend" / "app" / "state.js"

NODE = shutil.which("node")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    # Find the end of the parameter list first (tracking paren depth, since a
    # default value like `scope = {}` can itself contain balanced parens),
    # then the function body's opening brace is the first "{" after that -
    # a naive index("{", start) would instead match a `{}` default value
    # inside the parameter list itself.
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


def _run(items, division_filter="all", scope=None):
    source = STATE.read_text(encoding="utf-8")
    fn_source = _extract_function(source, "buildDashboardOverview")
    script = f"""
{fn_source}
const items = {json.dumps(items)};
console.log(JSON.stringify(buildDashboardOverview(items, {json.dumps(division_filter)}, {json.dumps(scope or {})})));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _item(doc_id, reconciled, amount, row_count=1):
    return {
        "document": {"id": doc_id, "reconciled": reconciled},
        "summary": {
            "amountAvailable": True,
            "documentTotals": {"rowCount": row_count, "amount": amount},
            "divisions": [],
        },
    }


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_unreconciled_documents_still_count_toward_the_grand_total():
    items = [_item("a", True, 100.0), _item("b", False, 50.0)]
    overview = _run(items)
    assert overview["totals"]["amount"] == 150.0
    assert overview["totals"]["documentCount"] == 2


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_unreconciled_amount_and_count_are_tracked_separately():
    items = [_item("a", True, 100.0), _item("b", False, 50.0), _item("c", False, 25.0)]
    overview = _run(items)
    assert overview["unreconciledDocumentCount"] == 2
    assert overview["unreconciledAmount"] == 75.0


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_all_reconciled_reports_zero_unreconciled():
    items = [_item("a", True, 100.0), _item("b", True, 50.0)]
    overview = _run(items)
    assert overview["unreconciledDocumentCount"] == 0
    assert overview["unreconciledAmount"] == 0


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_missing_reconciled_field_is_not_treated_as_unreconciled():
    """A document object without a `reconciled` key at all (e.g. an older
    shape, or a field genuinely absent) must not be miscounted - only an
    explicit reconciled === false counts, matching how document_summary_json
    only sets this key for status='complete' documents."""
    items = [{"document": {"id": "a"}, "summary": {"amountAvailable": True, "documentTotals": {"rowCount": 1, "amount": 10.0}, "divisions": []}}]
    overview = _run(items)
    assert overview["unreconciledDocumentCount"] == 0


# --- Dashboard/Products/Documents date-range consistency -------------------
#
# _computeDashboardOverview() in state.js must never silently drop a document
# whose per-document Division summary fetch failed: documentCount/rowCount
# are computed independently (from the same date-scoped documents/products
# arrays Products.js and Documents use), not from summing over `items`, and
# are passed in as `scope`. A failed summary should only shrink the
# amount/Division breakdown, and must be surfaced via isDataIncomplete /
# incompleteDocumentCount rather than silently vanishing.


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_scope_documentCount_and_rowCount_override_items_length():
    """Even when `items` is missing a document (its summary failed and was
    filtered out before calling buildDashboardOverview), the headline totals
    must reflect the independently-computed scope, not len(items)."""
    items = [_item("a", True, 100.0, row_count=3)]
    overview = _run(items, scope={"documentCount": 2, "rowCount": 7, "incompleteDocumentCount": 1})
    assert overview["totals"]["documentCount"] == 2
    assert overview["totals"]["rowCount"] == 7
    # The amount total still only reflects documents whose summary succeeded.
    assert overview["totals"]["amount"] == 100.0


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_incomplete_document_count_surfaces_data_incomplete_flag():
    items = [_item("a", True, 100.0)]
    overview = _run(items, scope={"documentCount": 1, "rowCount": 1, "incompleteDocumentCount": 1})
    assert overview["incompleteDocumentCount"] == 1
    assert overview["isDataIncomplete"] is True


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_no_failures_reports_data_complete():
    items = [_item("a", True, 100.0), _item("b", True, 50.0)]
    overview = _run(items, scope={"documentCount": 2, "rowCount": 2, "incompleteDocumentCount": 0})
    assert overview["incompleteDocumentCount"] == 0
    assert overview["isDataIncomplete"] is False


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_scope_omitted_falls_back_to_items_length_for_backward_compatibility():
    """Existing callers that don't pass a scope (e.g. these older tests) must
    keep working exactly as before the fix."""
    items = [_item("a", True, 100.0), _item("b", True, 50.0)]
    overview = _run(items)
    assert overview["totals"]["documentCount"] == 2
    assert overview["totals"]["rowCount"] == 2
    assert overview["isDataIncomplete"] is False


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_selected_division_totals_are_unaffected_by_scope():
    """A single-Division slice has no alternative data source - scope must
    not leak into it, only into the "all divisions" totals."""
    item = {
        "document": {"id": "a", "reconciled": True},
        "summary": {
            "amountAvailable": True,
            "documentTotals": {"rowCount": 5, "amount": 100.0},
            "divisions": [
                {"divisionCode": "D1", "divisionName": "Div 1", "rowCount": 5, "amount": 100.0},
            ],
        },
    }
    overview = _run([item], division_filter="D1", scope={"documentCount": 99, "rowCount": 99, "incompleteDocumentCount": 1})
    assert overview["totals"]["documentCount"] == 1
    assert overview["totals"]["rowCount"] == 5
