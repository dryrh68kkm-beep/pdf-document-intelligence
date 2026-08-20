"""Dashboard Phase 1 (Division rollup) - the CSV master file is the only
source of truth for the 6-division structure. Complements
test_department_groups.py's coverage of major_department_for (the
existing bare-department->bare-division mapping) with the new (code,
name) division-level API these tests exist to catch exactly what the
spec forbids: hard-coded division names, a 7th division minted for an
unmapped department, and prefix-normalization drift."""
from __future__ import annotations

from pdf_document_intelligence.templates.department_groups import (
    division_for_department,
    get_default_department_to_division_code,
    get_default_divisions,
    load_department_to_division_code,
    load_divisions,
)


def test_department_hierarchy_loads():
    divisions = load_divisions()
    assert len(divisions) > 0
    mapping = load_department_to_division_code()
    assert len(mapping) > 0


def test_exactly_six_distinct_divisions():
    divisions = get_default_divisions()
    codes = [code for code, _ in divisions]
    assert len(divisions) == 6
    assert len(set(codes)) == 6


def test_department_maps_to_correct_division():
    # from the real master file: HBA -> 04 DRY FOOD, HOUSEWARE -> 02 HOME LINE
    assert division_for_department("HBA") == ("04", "DRY FOOD")
    assert division_for_department("HOUSEWARE") == ("02", "HOME LINE")
    assert division_for_department("BUTCHERY") == ("05", "FRESH FOOD")


def test_prefix_normalization():
    # "0460 HBA" (with the store's leading numeric code, as it sometimes
    # appears in a Packing List) must resolve identically to bare "HBA".
    assert division_for_department("0460 HBA") == division_for_department("HBA")
    assert division_for_department("0250 STATIONERY & EDUTAINMENT") == division_for_department(
        "STATIONERY & EDUTAINMENT"
    )


def test_unmapped_department_returns_none_not_a_new_division():
    assert division_for_department("NOT_A_REAL_DEPARTMENT_XYZ") is None
    # and it must never silently appear inside the 6 real divisions
    divisions = get_default_divisions()
    names = {name for _, name in divisions}
    assert "NOT_A_REAL_DEPARTMENT_XYZ" not in names


def test_no_department_maps_to_more_than_one_division():
    mapping = get_default_department_to_division_code()
    # load_department_to_division_code is itself last-write-wins per dept;
    # verify the underlying CSV doesn't actually disagree with itself for
    # any department (a real collision would mean the master file, not
    # this mapping, is inconsistent).
    import csv
    from pathlib import Path

    path = Path(__file__).parent.parent.parent / "data" / "master_catalog.csv"
    seen: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            dept = row["DEPARTMENT_NAME"].strip()
            div = row["DIVISION_NAME"].strip()
            if dept in seen:
                assert seen[dept] == div, f"{dept} maps to both {seen[dept]} and {div}"
            else:
                seen[dept] = div
    assert len(mapping) > 0
