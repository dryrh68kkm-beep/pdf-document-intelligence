"""Repository data-safety guardrails.

These tests fail CI if real document/data file types are accidentally tracked.
Synthetic PDFs used by integration tests must be generated at runtime in tmp
folders, never stored in Git.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_no_pdf_documents_are_tracked():
    tracked = _tracked_files()
    pdfs = [path for path in tracked if path.lower().endswith(".pdf")]
    assert pdfs == [], f"PDF documents must not be committed: {pdfs}"


def test_operational_master_catalog_is_not_tracked():
    tracked = set(_tracked_files())
    assert "data/master_catalog.csv" not in tracked


def test_no_golden_expected_data_dumps_are_tracked():
    tracked = _tracked_files()
    dumps = [path for path in tracked if path.startswith("tests/golden/expected/")]
    assert dumps == [], f"Expected dumps derived from real documents are forbidden: {dumps}"


def test_gitignore_blocks_sensitive_runtime_inputs():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.pdf" in ignore
    assert "/data/*.csv" in ignore
    assert "/tests/golden/samples/*.pdf" in ignore
    assert "/tests/golden/expected/*.json" in ignore
