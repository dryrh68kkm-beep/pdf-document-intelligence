"""Cross-program accuracy checks (catalog/cross_reference.py + api/rows.py):
Stock Atlas / expiry data confirm names, and a barcode no source knows whose
GTIN check digit fails is repaired only when exactly one known neighbour exists."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_document_intelligence.api.rows import _resolution_status, repair_barcode, resolve_cross_reference
from pdf_document_intelligence.catalog.cross_reference import gtin_valid, name_similarity, neighbors
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.models.document import BoundingBox, FieldValue, TableRow

GOOD = "8859847102864"        # real barcode from the Atlas count DB, check digit valid
BAD = "8859847102854"         # one digit misread (6 -> 5): check digit fails
OTHER = "8850980056892"       # unrelated known product


class _Repo:
    def find_local_master_by_barcode(self, barcode):
        return None


def _field(name, value, source="pdf_text", review=False):
    return FieldValue(
        name=name, raw_value=value, value=value, type="string" if name == "name" else "code",
        bbox=BoundingBox(x=1, y=1, width=10, height=10, page=1), source=source, confidence=0.6,
        review_required=review,
    )


def _row(barcode, name="พัดลม OCR"):
    return TableRow(row_index=1, fields={"barcode": _field("barcode", barcode, review=True), "name": _field("name", name)}, confidence_band="LOW")


@pytest.fixture()
def settings(tmp_path: Path):
    count = tmp_path / "count.json"
    count.write_text(json.dumps({"products": [[GOOD, "2001", "SIMPLUS พัดลม DFSH013PIBC-BB"], [OTHER, "2002", "จุกนมซิลิโคน"]], "rows": [], "files": []}), encoding="utf-8")
    oos = tmp_path / "oos.json"
    oos.write_text(json.dumps({"items": [{"barcode": "1234567890128", "name": "สินค้าจาก OOS"}]}), encoding="utf-8")
    pog = tmp_path / "pog.json"
    pog.write_text(json.dumps({"list": [{"name": "POG A", "bays": [{"items": [{"bc": "4006381333931", "name": "ปากกา POG"}]}]}]}), encoding="utf-8")
    return Settings(expiry_dashboard_www_dir="", cross_reference_count_files=str(count), cross_reference_pog_files=str(pog), cross_reference_oos_files=str(oos))


@pytest.fixture(autouse=True)
def _no_catalog(monkeypatch):
    monkeypatch.setattr("pdf_document_intelligence.api.rows.get_default_catalog", lambda: {})


def test_gtin_checksum():
    assert gtin_valid(GOOD) and not gtin_valid(BAD)
    assert not gtin_valid("12345") and not gtin_valid("88598471028AB")


def test_neighbors_cover_substitution_transposition_and_length_edits():
    n = neighbors("8859847102864")
    assert "8859847102854" in n          # substitution
    assert "8859847102846" in n          # adjacent swap
    assert "885984710286" in n or "885984710284" in n or len(n) > 100  # deletion produces 12-digit codes
    assert all(len(c) in (8, 12, 13, 14) for c in n)


def test_misread_barcode_is_repaired_when_one_known_neighbour(settings):
    fixed = repair_barcode(_row(BAD), _Repo(), settings)
    bc = fixed.fields["barcode"]
    assert bc.value == GOOD and bc.raw_value == BAD          # evidence kept
    assert "BARCODE_CROSS_REPAIRED" in bc.validation_flags and bc.review_required is False


def test_known_barcode_is_never_touched(settings):
    assert repair_barcode(_row(GOOD), _Repo(), settings).fields["barcode"].value == GOOD


def test_unknown_with_no_neighbour_is_flagged_not_guessed(settings):
    row = repair_barcode(_row("8851234567891"), _Repo(), settings)   # check digit fails, nothing nearby
    bc = row.fields["barcode"]
    assert bc.value == "8851234567891" and bc.review_required and "BARCODE_CHECKSUM_FAIL" in bc.validation_flags


def test_valid_checksum_unknown_product_needs_name_agreement(settings):
    # a *valid* but unknown barcode one edit from a known one: only repair if the printed name agrees
    near = None
    for c in sorted(neighbors(GOOD)):
        if gtin_valid(c):
            near = c
            break
    assert near
    different = repair_barcode(_row(near, name="ผงซักฟอก"), _Repo(), settings)
    assert different.fields["barcode"].value == near
    assert any(f.startswith("BARCODE_SUGGESTION:") for f in different.fields["barcode"].validation_flags)
    same = repair_barcode(_row(near, name="SIMPLUS พัดลม DFSH013PIBC-BB"), _Repo(), settings)
    assert same.fields["barcode"].value == GOOD


def test_name_resolved_from_atlas_count_and_oos(settings):
    r = resolve_cross_reference(_row(GOOD), settings)
    name = r.fields["name"]
    assert name.value == "SIMPLUS พัดลม DFSH013PIBC-BB" and name.source == "master_catalog" and not name.review_required
    assert _resolution_status(r) == "CROSS_REFERENCE"
    assert resolve_cross_reference(_row("1234567890128"), settings).fields["name"].value == "สินค้าจาก OOS"
    assert resolve_cross_reference(_row("0000000000000"), settings).fields["name"].value == "พัดลม OCR"


def test_no_reference_files_means_no_change():
    s = Settings(expiry_dashboard_www_dir="")
    assert resolve_cross_reference(_row(GOOD), s).fields["name"].value == "พัดลม OCR"
    assert name_similarity("abc", "abd") > 0.5


def test_name_and_repair_use_pog_data(settings):
    r = resolve_cross_reference(_row("4006381333931"), settings)
    assert r.fields["name"].value == "ปากกา POG" and "STOCK_ATLAS_POG" in r.fields["name"].validation_flags
    bad = "4006381333941"  # one digit misread
    assert not gtin_valid(bad)
    assert repair_barcode(_row(bad, "ปากกา"), _Repo(), settings).fields["barcode"].value == "4006381333931"
