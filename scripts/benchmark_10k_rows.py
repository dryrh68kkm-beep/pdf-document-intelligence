"""Synthetic 10,000-row performance benchmark (spec item 30). Not part of
the pytest suite (it's a manual perf check, not a pass/fail regression
gate) - run directly: python scripts/benchmark_10k_rows.py
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tempfile

from pdf_document_intelligence.api.aggregate import build_dashboard_state
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository
from tests.unit.db_helpers import make_result, make_row

N_ROWS = 10_000
DEPARTMENTS = [f"DEPT_{i}" for i in range(20)]


def main() -> None:
    db_path = Path(tempfile.mkdtemp()) / "bench.db"
    repo = Repository(open_independent_connection(db_path))
    repo.create_document("bench-doc", sha256="bench", filename="bench.pdf", file_size=1)
    repo.set_document_complete("bench-doc", 1, {"confidence": 0.9})

    rows = []
    for i in range(N_ROWS):
        dept = random.choice(DEPARTMENTS)
        rows.append(make_row(i, dept, f"BC{i:010d}", f"ART{i}", f"Product {i}", 1.0, 2, 3))
    tables = {}
    for r, dept in zip(rows, [random.choice(DEPARTMENTS) for _ in rows]):
        pass  # departments are already baked into each row's own table below

    grouped: dict[str, list] = {}
    for i, r in enumerate(rows):
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        grouped.setdefault(dept, []).append(r)
    result = make_result("bench-doc", "bench.pdf", list(grouped.items()))

    t0 = time.perf_counter()
    outcome = repo.replace_document_rows("bench-doc", [])  # warm up
    from pdf_document_intelligence.api.rows import persist_document_result

    t0 = time.perf_counter()
    persist_document_result("bench-doc", result, repo)
    t_insert = time.perf_counter() - t0
    print(f"Batch insert {N_ROWS:,} rows: {t_insert:.3f}s ({N_ROWS / t_insert:,.0f} rows/s)")

    t0 = time.perf_counter()
    state = build_dashboard_state(repo)
    t_dashboard = time.perf_counter() - t0
    print(f"Dashboard aggregation over {state['rowCount']:,} rows: {t_dashboard:.3f}s")

    t0 = time.perf_counter()
    dept_rows = repo.list_product_rows(document_id="bench-doc")
    t_dept = time.perf_counter() - t0
    print(f"Department/document row query ({len(dept_rows):,} rows): {t_dept:.3f}s")

    t0 = time.perf_counter()
    matches = [r for r in repo.list_product_rows() if "Product 500" in (r["resolved_product_name"] or "")]
    t_search = time.perf_counter() - t0
    print(f"In-Python search scan over {N_ROWS:,} rows ({len(matches)} matches): {t_search:.3f}s")

    t0 = time.perf_counter()
    one_row = repo.get_product_row(dept_rows[0]["id"])
    t_single = time.perf_counter() - t0
    print(f"Single indexed row lookup: {t_single * 1000:.2f}ms")


if __name__ == "__main__":
    main()
