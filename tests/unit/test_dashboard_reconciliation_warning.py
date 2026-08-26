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


def _run(items, division_filter="all"):
    source = STATE.read_text(encoding="utf-8")
    fn_source = _extract_function(source, "buildDashboardOverview")
    script = f"""
{fn_source}
const items = {json.dumps(items)};
console.log(JSON.stringify(buildDashboardOverview(items, {json.dumps(division_filter)})));
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
