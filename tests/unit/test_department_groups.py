"""Unit tests for the Department -> Division rollup (display-only - see
templates/department_groups.py for why this is backed by a real supplied
master hierarchy rather than a guessed pattern match)."""
from __future__ import annotations

from pdf_document_intelligence.templates.department_groups import major_department_for


def test_known_departments_map_to_their_real_division():
    cases = {
        "BEVERAGE": "DRY FOOD",
        "SWEETED GROCE.1": "DRY FOOD",
        "SWEETED GROCE.2": "DRY FOOD",
        "SWEETED GROCE.2_SME": "DRY FOOD",
        "SALTED GROCERY": "DRY FOOD",
        "SALTED GROCERY_SME": "DRY FOOD",
        "STATIONERY & EDUTAINMENT": "HOME LINE",
        "BUTCHERY": "FRESH FOOD",
        "SMALL APPLIANCE": "HARD LINE",
        "PRESCRIPTION": "PHARMACY",
    }
    for dept, division in cases.items():
        assert major_department_for(dept) == division


def test_unknown_department_is_its_own_major():
    """A department name the supplied master hierarchy doesn't cover must
    never be guessed into a division - it stays its own group."""
    assert major_department_for("SOME NEW DEPARTMENT NOT IN MASTER DATA") == "SOME NEW DEPARTMENT NOT IN MASTER DATA"


def test_all_bpdc_sample_departments_are_covered():
    """Every department name the real BPDC sample actually produces
    (tests/golden/expected/BPDC_91101_190826.json) must resolve to a real
    division, not fall back to itself - regression guard against the
    master data file drifting out of sync with what extraction produces."""
    import json
    from pathlib import Path

    expected = json.loads(
        (Path(__file__).parent.parent / "golden" / "expected" / "BPDC_91101_190826.json").read_text(encoding="utf-8")
    )
    for dept in expected["departments"]:
        name = dept["name"]
        assert major_department_for(name) != name, f"{name!r} has no division mapping in department_divisions.csv"
