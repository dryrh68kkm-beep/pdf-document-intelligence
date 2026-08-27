"""PR17 (Review Queue UX): the same dead-button bug PR16 fixed in Products
existed in the Review Queue too - the "จัดการ" column rendered an eye icon
with data-row-action="view", but renderDataTable() was never given an
onRowAction callback here, so the click did nothing (and, per
dataTable.js's own row-click guard, also silently prevented the row's
onRowClick from firing for that one click). Clicking anywhere else in the
row already opens the detail panel and shows the evidence panel
(onRowClick), so a second "view" affordance was redundant even if it had
worked - the button's real, distinct value in a triage queue is a
one-click resolve without opening the panel first.

review.js has no DOM-free pure function to execute directly, matching the
project's established pattern for this bug class - these are source-level
regression guards. Live-verified in a real browser during development:
clicking the resolve action in the Review Queue shows the confirmation
and, on confirm, calls the real POST /api/review/{rowId}/confirm endpoint
end to end, same as the equivalent Products flow.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "frontend" / "app" / "views" / "review.js"
REVIEW_ACTIONS = ROOT / "frontend" / "app" / "reviewActions.js"


def test_review_queue_wires_a_real_onrowaction_not_a_dead_button():
    source = REVIEW.read_text(encoding="utf-8")
    assert "onRowAction:" in source
    assert 'data-row-action="resolve"' in source
    # Regression guard for the original bug: the old unconditional,
    # never-wired "view" action must be gone.
    assert 'data-row-action="view"' not in source


def test_review_queue_action_reuses_the_shared_resolve_helper():
    """Must not duplicate the confirm-dialog/api-call/error-handling block
    that already exists for Products (PR16) - both views import the same
    function."""
    source = REVIEW.read_text(encoding="utf-8")
    assert 'from "../reviewActions.js"' in source
    assert "confirmMarkResolved(store, row)" in source


def test_shared_resolve_helper_calls_the_real_confirm_endpoint():
    source = REVIEW_ACTIONS.read_text(encoding="utf-8")
    assert "api.confirmReview(row.rowId)" in source
    assert "store.refreshAll()" in source
    # A failed confirm must surface an error, not fail silently.
    assert "show-error" in source
