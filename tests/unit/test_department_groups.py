"""Unit tests for Department -> Division rollup using only synthetic test data."""
from __future__ import annotations

from pdf_document_intelligence.templates.department_groups import major_department_for


def test_known_departments_map_from_synthetic_hierarchy():
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
    assert major_department_for("SOME NEW DEPARTMENT NOT IN TEST HIERARCHY") == "SOME NEW DEPARTMENT NOT IN TEST HIERARCHY"


def test_synthetic_hierarchy_covers_supported_test_departments():
    for name in (
        "BEVERAGE",
        "HBA",
        "HOUSEWARE",
        "FACE & COSMETICS",
        "BUTCHERY",
        "SMALL APPLIANCE",
        "PRESCRIPTION",
    ):
        assert major_department_for(name) != name
