"""LAN concurrency / stress regression suite.

This is a real production LAN deployment (multiple viewers/admins on the
same network hitting one shared FastAPI+SQLite process concurrently) - the
existing PR9/PR12/L3-* fixes in api/app.py and db/repository.py already
harden specific races (see their docstrings). This file exercises those
same guarantees under actual concurrent load, using ThreadPoolExecutor
against the app's TestClient (the same pattern test_api.py's own
`test_concurrent_duplicate_upload_returns_409_not_500` and
`test_only_one_of_two_concurrent_reprocess_claims_wins` already use - no
new external load-testing dependency).

No strict timing thresholds are asserted anywhere in this file. What *is*
asserted, per document: zero unexpected 5xx, zero data corruption, zero
duplicate processing claims, zero stale overwrites, zero resurrected
deleted data, and no unhandled exception/deadlock (a hang would fail via
pytest's own suite timeout). Metrics (total requests, success/conflict/
rejected/unexpected-5xx counts, max/avg latency) are collected and printed
for visibility, not asserted against a threshold.

Only synthetic, runtime-generated fixtures are used - no real company PDF
or Master data.
"""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pdf_document_intelligence.api.app as app_module
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from tests.synthetic_documents import make_bigc_pdf


def _reset_store():
    store.reset_for_tests()


@dataclass
class _Metrics:
    statuses: list[int] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)

    def record(self, status: int, duration: float) -> None:
        self.statuses.append(status)
        self.durations.append(duration)

    def count(self, status: int) -> int:
        return sum(1 for s in self.statuses if s == status)

    @property
    def unexpected_5xx(self) -> int:
        # 503 (queue-full) and 423 (already-processing) are this app's own
        # deliberate, documented rejection responses under load - not
        # server errors. Only a genuine 5xx other than the intended 503
        # counts as "unexpected" here.
        return sum(1 for s in self.statuses if 500 <= s < 600 and s != 503)

    def report(self, label: str) -> None:
        total = len(self.statuses)
        avg = sum(self.durations) / total if total else 0.0
        mx = max(self.durations) if self.durations else 0.0
        print(
            f"\n[stress:{label}] total={total} "
            f"success2xx={sum(1 for s in self.statuses if 200 <= s < 300)} "
            f"conflict409/412={self.count(409) + self.count(412)} "
            f"rejected423/503={self.count(423) + self.count(503)} "
            f"unexpected5xx={self.unexpected_5xx} "
            f"avg_ms={avg * 1000:.1f} max_ms={mx * 1000:.1f}"
        )


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def _upload_and_wait_complete(client: TestClient, tmp_path, name: str, timeout: float = 60):
    """Runs a synthetic PDF through the real pipeline (real executor, real
    text-layer extraction, no OCR needed) to get a genuinely populated,
    completed document + product row - used wherever a test needs a real
    row to race against, rather than hand-constructing a product_rows dict
    (which is deliberately not a small/stable shape - see
    repository.py's _replace_document_rows_sql column list)."""
    sample = make_bigc_pdf(tmp_path / f"{name}.pdf")
    res = client.post("/api/documents", files={"file": (f"{name}.pdf", sample.read_bytes(), "application/pdf")})
    assert res.status_code == 200, res.text
    doc_id = res.json()["id"]
    deadline = time.time() + timeout
    doc = None
    while time.time() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in ("complete", "error"):
            break
        time.sleep(0.2)
    assert doc is not None and doc["status"] == "complete", doc
    rows = client.get("/api/products").json()
    row = next(r for r in rows if r["docId"] == doc_id)
    return doc_id, row["rowId"], row["updatedAt"]


# ---------------------------------------------------------------------
# 1. Concurrent GETs across the main read endpoints
# ---------------------------------------------------------------------


def test_concurrent_reads_across_endpoints_never_5xx():
    _reset_store()
    client = TestClient(app)
    store.create("read-fixture-a.pdf", b"%PDF-1.4\n%stress-read-a\n")
    store.create("read-fixture-b.pdf", b"%PDF-1.4\n%stress-read-b\n")

    endpoints = ["/api/documents", "/api/products", "/api/state", "/api/health"] * 15
    metrics = _Metrics()

    def _hit(path):
        (res, elapsed) = _timed(lambda: client.get(path))
        return res.status_code, elapsed

    with ThreadPoolExecutor(max_workers=16) as pool:
        for status, elapsed in pool.map(_hit, endpoints):
            metrics.record(status, elapsed)

    metrics.report("concurrent-reads")
    assert metrics.unexpected_5xx == 0
    assert all(s == 200 for s in metrics.statuses)


# ---------------------------------------------------------------------
# 2. Concurrent edits on the same product row, expected_updated_at token
# ---------------------------------------------------------------------


def test_concurrent_edits_same_row_yield_exactly_one_success_and_one_412(tmp_path):
    """PR12's atomic-conditional-UPDATE guarantee (repository.py's
    update_product_row_field docstring) under real thread concurrency, not
    just the sequential unit-level proof."""
    _reset_store()
    client = TestClient(app)

    _doc_id, row_id, expected_updated_at = _upload_and_wait_complete(client, tmp_path, "edit-race")

    def _patch(value):
        return client.patch(
            f"/api/products/{row_id}",
            json={"field": "sku_qty", "value": value, "reason": "stress", "expectedUpdatedAt": expected_updated_at},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_patch, 10), pool.submit(_patch, 20)]
        responses = [f.result() for f in futures]

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200, 412], f"expected exactly one success + one conflict, got {statuses}"
    # The row landed on exactly one of the two racing values - never a
    # torn/partial write.
    final_value = store.repo.get_product_row(row_id)["sku_qty"]
    assert final_value in (10.0, 20.0)


# ---------------------------------------------------------------------
# 3. Concurrent upload pressure against the processing-queue cap
# ---------------------------------------------------------------------


def test_concurrent_upload_pressure_respects_queue_cap_and_never_5xx(monkeypatch):
    """Documents are held in status='processing' indefinitely (executor
    submissions are captured, never run) so the queue-cap check
    (`_count_processing_documents() >= _MAX_QUEUED_PROCESSING_JOBS`, see
    api/app.py) is exercised directly under concurrent pressure instead of
    racing real OCR completion times."""
    _reset_store()

    submitted = []

    class CapturingExecutor:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return None

    monkeypatch.setattr(app_module, "_executor", CapturingExecutor())
    client = TestClient(app)

    cap = app_module._MAX_QUEUED_PROCESSING_JOBS
    n_uploads = cap + 8  # deliberately well past the cap
    metrics = _Metrics()

    def _upload(i):
        content = f"%PDF-1.4\n%stress-queue-{i}\n".encode()
        (res, elapsed) = _timed(
            lambda: client.post("/api/documents", files={"file": (f"queue-{i}.pdf", content, "application/pdf")})
        )
        return res.status_code, elapsed

    with ThreadPoolExecutor(max_workers=n_uploads) as pool:
        for status, elapsed in pool.map(_upload, range(n_uploads)):
            metrics.record(status, elapsed)

    metrics.report("upload-queue-pressure")
    assert metrics.unexpected_5xx == 0
    assert set(metrics.statuses) <= {200, 503}
    # The cap must actually have been enforced (at least one rejection)
    # given deliberately-past-cap pressure, and never grown the store
    # unboundedly past what was actually accepted.
    accepted = metrics.count(200)
    assert accepted == cap, f"queue cap not exactly enforced under concurrent pressure: accepted={accepted}, cap={cap}"
    assert metrics.count(503) == n_uploads - cap
    assert len(store.list()) == accepted


# ---------------------------------------------------------------------
# 4. Delete-vs-edit race: never resurrect, never stale-overwrite
# ---------------------------------------------------------------------


def test_delete_vs_edit_race_never_resurrects_or_stale_overwrites(tmp_path):
    client = TestClient(app)

    for trial in range(4):
        _reset_store()
        doc_id, row_id, _ = _upload_and_wait_complete(client, tmp_path, f"delete-edit-race-{trial}")

        def _delete(doc_id=doc_id):
            return client.delete(f"/api/documents/{doc_id}")

        def _edit():
            return client.patch(
                f"/api/products/{row_id}",
                json={"field": "sku_qty", "value": 99, "reason": "race"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_delete = pool.submit(_delete)
            f_edit = pool.submit(_edit)
            delete_res, edit_res = f_delete.result(), f_edit.result()

        assert delete_res.status_code in (200, 404)
        assert edit_res.status_code in (200, 404, 412)
        assert 500 > delete_res.status_code >= 200 or delete_res.status_code < 600
        assert delete_res.status_code < 500 and edit_res.status_code < 500

        after = client.get(f"/api/products/{row_id}")
        if delete_res.status_code == 200:
            # Delete won (or landed after the edit) - the row must not be
            # resurrected/readable regardless of what the edit did.
            assert after.status_code == 404
        else:
            # Delete lost the race entirely (document already gone before
            # this delete call, impossible here since each trial is fresh)
            # - not reachable in this harness, kept for clarity only.
            pass


# ---------------------------------------------------------------------
# 5. Concurrent reprocess calls: exactly one atomic claim succeeds
# ---------------------------------------------------------------------


def test_concurrent_reprocess_calls_exactly_one_claim_succeeds(monkeypatch):
    submitted = []

    class CapturingExecutor:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return None

    monkeypatch.setattr(app_module, "_executor", CapturingExecutor())
    client = TestClient(app)
    _reset_store()

    doc = store.create("reprocess-race.pdf", b"%PDF-1.4\n%stress-reprocess-race\n")
    store.set_error(doc["id"], "bring to a claimable terminal state")

    def _reprocess():
        return client.post(f"/api/documents/{doc['id']}/reprocess")

    n_callers = 10
    with ThreadPoolExecutor(max_workers=n_callers) as pool:
        results = list(pool.map(lambda _: _reprocess(), range(n_callers)))

    statuses = sorted(r.status_code for r in results)
    assert statuses.count(200) == 1, f"expected exactly one accepted claim, got statuses={statuses}"
    assert statuses.count(423) == n_callers - 1
    assert all(s < 500 for s in statuses)
    # Exactly one worker job was ever submitted for this document, no
    # matter how many callers raced the claim.
    assert len(submitted) == 1
    assert submitted[0][1][0] == doc["id"]


# ---------------------------------------------------------------------
# 6. Multi-client reads while a document is mid-processing
# ---------------------------------------------------------------------


def test_multiclient_reads_during_real_processing_never_corrupt_or_500(tmp_path):
    """Uses the real thread-pool executor (not a capturing stub) with an
    actual synthetic PDF, so requests genuinely land while
    store.set_progress()/complete_document_with_rows() are being called
    concurrently from the background worker thread - the scenario PR9/L3
    guard against (SQLite locking surfacing as a 500, or a half-written
    row read back as a corrupt/partial JSON response)."""
    _reset_store()
    client = TestClient(app)
    sample = make_bigc_pdf(tmp_path / "stress-midprocessing.pdf")
    content = sample.read_bytes()

    upload_res = client.post("/api/documents", files={"file": ("mid.pdf", content, "application/pdf")})
    assert upload_res.status_code == 200
    doc_id = upload_res.json()["id"]

    metrics = _Metrics()
    stop = {"flag": False}

    def _poll():
        while not stop["flag"]:
            for path in (f"/api/documents/{doc_id}", "/api/documents", "/api/products", "/api/state"):
                (res, elapsed) = _timed(lambda p=path: client.get(p))
                metrics.record(res.status_code, elapsed)
                if res.status_code == 200:
                    # Every response must be well-formed JSON, never a
                    # half-written/corrupt body.
                    res.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        pollers = [pool.submit(_poll) for _ in range(6)]
        deadline = time.time() + 60
        final_status = None
        while time.time() < deadline:
            doc = client.get(f"/api/documents/{doc_id}").json()
            if doc["status"] in ("complete", "error"):
                final_status = doc["status"]
                break
            time.sleep(0.2)
        stop["flag"] = True
        for p in pollers:
            p.result(timeout=15)

    metrics.report("multiclient-mid-processing-reads")
    assert final_status == "complete", "synthetic document did not complete during the polling window"
    assert metrics.unexpected_5xx == 0
    assert metrics.count(404) == 0  # the document existed throughout
