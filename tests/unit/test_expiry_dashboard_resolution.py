"""api/rows.py's resolve_expiry_dashboard: the third resolution tier that
checks expiry-dashboard's own live daily product list for a barcode this
pipeline couldn't otherwise resolve via the Official/Local Master
catalogs. Mirrors resolve_local_master's own test shape."""
from __future__ import annotations

from pathlib import Path

from pdf_document_intelligence.api.rows import resolve_expiry_dashboard
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.models.document import BoundingBox, FieldValue, TableRow


def _bbox() -> BoundingBox:
    return BoundingBox(x=1, y=1, width=10, height=10, page=1)


def _field(name: str, value: str, source: str = "pdf_text") -> FieldValue:
    return FieldValue(name=name, raw_value=value, value=value, type="string" if name == "name" else "code", bbox=_bbox(), source=source, confidence=0.6)


def _row(barcode: str, name_value: str, name_source: str = "pdf_text") -> TableRow:
    return TableRow(
        row_index=1,
        fields={"barcode": _field("barcode", barcode), "name": _field("name", name_value, source=name_source)},
        confidence_band="MEDIUM",
    )


def _settings_for(tmp_path: Path) -> Settings:
    return Settings(expiry_dashboard_www_dir=str(tmp_path))


def test_promotes_name_on_a_match(tmp_path: Path):
    (tmp_path / "data.csv").write_text(
        "BAR_CODE,DESCRIPTION,SUB_DEPT_NAME\n8850000000001,Perrier 1500ml,CHILLED\n", encoding="utf-8"
    )
    row = _row("8850000000001", "PRRIER OCR GUESS")
    resolved = resolve_expiry_dashboard(row, _settings_for(tmp_path))
    name = resolved.fields["name"]
    assert name.value == "Perrier 1500ml"
    assert name.source == "master_catalog"
    assert name.confidence == 1.0
    assert name.review_required is False
    assert "EXPIRY_DASHBOARD_MATCH" in name.validation_flags


def test_leaves_row_unchanged_when_barcode_not_found(tmp_path: Path):
    (tmp_path / "data.csv").write_text("BAR_CODE,DESCRIPTION,SUB_DEPT_NAME\n", encoding="utf-8")
    row = _row("9999999999999", "OCR GUESS")
    resolved = resolve_expiry_dashboard(row, _settings_for(tmp_path))
    assert resolved.fields["name"].value == "OCR GUESS"
    assert resolved.fields["name"].source == "pdf_text"


def test_does_not_override_an_already_resolved_master_catalog_name(tmp_path: Path):
    (tmp_path / "data.csv").write_text(
        "BAR_CODE,DESCRIPTION,SUB_DEPT_NAME\n8850000000001,Expiry Dashboard Name,CHILLED\n", encoding="utf-8"
    )
    row = _row("8850000000001", "Official Master Name", name_source="master_catalog")
    resolved = resolve_expiry_dashboard(row, _settings_for(tmp_path))
    assert resolved.fields["name"].value == "Official Master Name"


def test_disabled_when_www_dir_is_empty():
    row = _row("8850000000001", "OCR GUESS")
    resolved = resolve_expiry_dashboard(row, Settings(expiry_dashboard_www_dir=""))
    assert resolved.fields["name"].value == "OCR GUESS"
