"""PR14 (auto refresh without state loss): the product detail panel is
rebuilt on every store.set(), including a refreshAll() triggered by
something unrelated to the row being edited - most commonly another LAN
user's unrelated upload finishing processing (main.js's poll loop calls
refreshAll() the moment any document's status flips out of "processing").
pendingEdits already survives that re-render (module-level state, checked
before falling back to the server value), but destroying and recreating
the <input> via innerHTML still kicked focus out and dropped the cursor
position mid-keystroke - jarring and easy to mistake for the edit itself
having been lost.

detailPanel.js has no pure, DOM-free function to execute directly (it
needs a real DOM + the api/store modules), so - matching the project's
established pattern for this class of bug (products.js's local filter
box, dashboard.js's product search box) - this is a source-level
regression guard: the same capture-before/restore-after technique must be
present and correctly ordered relative to the innerHTML rewrite. Verified
live in a real browser during development (headless Chromium): focus and
cursor position on a mid-edit field survive a renderProductDetail() call
triggered while typing.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DETAIL_PANEL = ROOT / "frontend" / "app" / "components" / "detailPanel.js"


def _source() -> str:
    return DETAIL_PANEL.read_text(encoding="utf-8")


def test_active_element_is_captured_before_the_innerhtml_rewrite():
    source = _source()
    capture_idx = source.index("container.contains(document.activeElement)")
    rewrite_idx = source.index("container.innerHTML = `", capture_idx)
    assert capture_idx < rewrite_idx, "focus must be captured before the DOM is torn down and rebuilt"


def test_focus_is_restored_after_the_innerhtml_rewrite_using_data_field():
    source = _source()
    rewrite_idx = source.index("container.innerHTML = `")
    restore_idx = source.index('.dp-edit-input[data-field="${focusedField}"]', rewrite_idx)
    assert rewrite_idx < restore_idx, "focus must be restored only after the new DOM exists"
    # Restoring focus alone isn't enough mid-keystroke - the cursor position
    # itself (not just which field has focus) must be reapplied too.
    assert "setSelectionRange" in source


def test_reason_textarea_is_also_covered_not_just_the_editable_fields():
    """The reason textarea (#dpReasonText) is a real place a user can be
    typing when an unrelated refresh fires - it must not be treated as a
    field this fix forgot."""
    source = _source()
    assert '"dpReasonText"' in source
    assert 'container.querySelector("#dpReasonText")' in source
