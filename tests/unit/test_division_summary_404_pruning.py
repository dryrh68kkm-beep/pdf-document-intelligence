"""Live report (screenshot, browser console): the Dashboard kept warning
"ไม่สามารถดึงสรุป Division...ได้" and the console showed the real cause
once the diagnosability fix (state.js's _getDivisionSummary console.error)
landed - "404 404 document not found" for a specific document ID.

Root cause: divisions.py's build_division_summary() -> _active_document()
only ever 404s when repo.get_document() finds the row genuinely missing or
soft-deleted (repo.list_documents(), which populates state.documents in
the first place, already filters deleted_at IS NULL) - so a 404 here is
authoritative proof the document is gone, not a transient failure worth
retrying. The document was still present in the Dashboard's in-memory
`state.documents` only because that array had gone stale relative to the
backend (e.g. deleted from another tab/session, or an earlier action in
this one, since this tab's document list was last fetched) - and because
_getDivisionSummary's per-document result cache never re-fetches once
poisoned, that ghost entry would otherwise re-trigger the same warning on
every future render until the page happened to get a full reload.

Fix: on a 404 specifically, _getDivisionSummary now prunes the document
from state.documents immediately, so a ghost entry self-heals right away
instead of nagging forever.

Follow-up user request: check proactively too, not only reactively after
a 404 comes back. Before firing the request (or even returning a cached
result), _getDivisionSummary now checks whether docId is still present in
state.documents at all - if not, it skips the network round-trip entirely
and drops any cache entry for that ID. This also closes a gap the 404
prune alone left open: a docId that was cached *successfully* before
being deleted would otherwise keep being served from cache forever with
no existence check at all, silently feeding stale numbers into the
Dashboard - worse than the "incomplete" warning it was supposed to avoid.

state.js's _getDivisionSummary is a Store class method (uses `this.set`,
`this._divisionCache`, `api.getDivisions`) rather than a pure function, so
unlike the Node-execution tests elsewhere in this suite (see
test_dashboard_focus_items.py) this is a source-level regression guard,
matching this project's established pattern for that bug class (see
test_documents_reprocess_all.py).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "frontend" / "app" / "state.js"


def _source() -> str:
    return STATE.read_text(encoding="utf-8")


def _get_division_summary_body() -> str:
    source = _source()
    start = source.index("async _getDivisionSummary(docId)")
    end = source.index("\n  }\n\n  async _computeDashboardOverview", start)
    return source[start:end]


def test_a_404_from_the_divisions_endpoint_prunes_the_document_from_state():
    body = _get_division_summary_body()
    assert 'err.status === 404' in body
    assert "this.state.documents.filter((doc) => doc.id !== docId)" in body


def test_the_failure_is_still_logged_and_cached_before_any_pruning_check():
    """The diagnosability fix (console.error with the real status/message/
    diagnosticId) and the null cache-write must both still happen
    unconditionally - the 404 prune is an addition, not a replacement."""
    body = _get_division_summary_body()
    assert "console.error(" in body
    assert "this._divisionCache.set(docId, null);" in body
    log_index = body.index("console.error(")
    cache_index = body.index("this._divisionCache.set(docId, null);")
    prune_index = body.index("err.status === 404")
    assert log_index < cache_index < prune_index


def test_a_non_404_failure_does_not_prune_the_document():
    """A transient/real backend error (500, network failure, ...) must not
    make a genuinely-existing document vanish from the Documents/Products/
    Dashboard views - only an authoritative 404 justifies that."""
    body = _get_division_summary_body()
    prune_start = body.index("if (err.status === 404) {")
    prune_end = body.index("\n      }", prune_start)
    prune_block = body[prune_start : prune_end + len("\n      }")]
    # The filter/set call must live inside the 404-only branch, not at the
    # catch block's top level.
    assert "this.set({ documents:" in prune_block
    before_branch = body[: body.index("if (err.status === 404) {")]
    assert "this.set({ documents:" not in before_branch


def test_a_docid_no_longer_in_state_documents_is_checked_before_the_cache_and_before_any_network_call():
    body = _get_division_summary_body()
    existence_check_index = body.index("!this.state.documents.some((doc) => doc.id === docId)")
    cache_read_index = body.index("this._divisionCache.has(docId)")
    api_call_index = body.index("api.getDivisions(docId)")
    assert existence_check_index < cache_read_index < api_call_index


def test_a_docid_no_longer_in_state_documents_drops_any_stale_cache_entry():
    """A docId cached from *before* it was deleted must not keep being
    served from cache forever - the existence check must clear it, not
    just skip the network call."""
    body = _get_division_summary_body()
    guard_start = body.index("!this.state.documents.some((doc) => doc.id === docId)")
    guard_block_end = body.index("\n    }", guard_start)
    guard_block = body[guard_start : guard_block_end + len("\n    }")]
    assert "this._divisionCache.delete(docId);" in guard_block
    assert "return null;" in guard_block
