"""Incremental Dashboard refresh (user request: re-fetching every document/
row on every refresh got slow as the document count grew) - mergeById()/
maxUpdatedAt() in state.js are pure functions (no DOM/imports), executed
directly via Node for real behavioral coverage, matching this project's
established pattern (see test_dashboard_focus_items.py). The backend half
(list_documents_since()/list_product_rows_since(), and the effective-
updated_at correctness this relies on) is covered by
tests/integration/test_incremental_refresh.py.
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


def _run(fn_name: str, *args):
    source = STATE.read_text(encoding="utf-8")
    fn = _extract_function(source, fn_name)
    args_js = ", ".join(json.dumps(a) for a in args)
    script = f"""
{fn}
console.log(JSON.stringify({fn_name}({args_js})));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_merge_by_id_adds_new_entries():
    existing = [{"id": "a", "v": 1}]
    delta = [{"id": "b", "v": 2}]
    result = _run("mergeById", existing, delta, "id")
    assert sorted(item["id"] for item in result) == ["a", "b"]


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_merge_by_id_updates_existing_entry_in_place():
    existing = [{"id": "a", "v": 1}, {"id": "b", "v": 1}]
    delta = [{"id": "a", "v": 99}]
    result = _run("mergeById", existing, delta, "id")
    by_id = {item["id"]: item["v"] for item in result}
    assert by_id == {"a": 99, "b": 1}


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_merge_by_id_removes_entry_with_deleted_at():
    existing = [{"id": "a", "v": 1}, {"id": "b", "v": 1}]
    delta = [{"id": "a", "v": 1, "deletedAt": "2026-01-01T00:00:00+00:00"}]
    result = _run("mergeById", existing, delta, "id")
    assert [item["id"] for item in result] == ["b"]


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_merge_by_id_with_empty_delta_returns_same_shape():
    existing = [{"id": "a", "v": 1}]
    result = _run("mergeById", existing, [], "id")
    assert result == existing


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_max_updated_at_picks_the_highest_value():
    delta = [{"updatedAt": "2026-01-01T00:00:00+00:00"}, {"updatedAt": "2026-01-03T00:00:00+00:00"}]
    assert _run("maxUpdatedAt", delta, None) == "2026-01-03T00:00:00+00:00"


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_max_updated_at_keeps_current_cursor_when_delta_is_empty():
    assert _run("maxUpdatedAt", [], "2026-01-01T00:00:00+00:00") == "2026-01-01T00:00:00+00:00"


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_max_updated_at_never_goes_backwards():
    delta = [{"updatedAt": "2025-01-01T00:00:00+00:00"}]  # older than the current cursor
    assert _run("maxUpdatedAt", delta, "2026-01-01T00:00:00+00:00") == "2026-01-01T00:00:00+00:00"



def _method_source(source: str, signature: str) -> str:
    start = source.index(signature)
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


def test_refresh_documents_uses_the_incremental_cursor_after_bootstrap():
    """Regression for the live UI poll/upload path: once _doRefreshAll()
    has established the cursor, refreshDocuments must ask only for the
    delta instead of re-fetching every historical document every 1.5/5s
    or every time a new PDF is dropped."""
    source = STATE.read_text(encoding="utf-8")
    method = _method_source(source, "async refreshDocuments(")

    assert "const since = this._lastDocSyncedAt" in method
    assert "api.listDocuments(since)" in method
    assert 'mergeById(this.state.documents, delta, "id")' in method
    assert "this._lastDocSyncedAt = maxUpdatedAt(delta, since)" in method
    assert "api.listDocuments()" not in method


def test_poll_and_upload_paths_reuse_refresh_documents_delta_sync():
    """Both ways a user introduces a new file should share the same
    incremental document sync rather than having a hidden full-list path."""
    main = (ROOT / "frontend" / "app" / "main.js").read_text(encoding="utf-8")

    # Manual Add Files calls this immediately after POST; pollLoop calls it
    # for auto-inbox files and for progress transitions.
    assert main.count("store.refreshDocuments({ silent: true })") >= 3
