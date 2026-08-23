"""Excel export must never let an untrusted string (a PDF/OCR product name
or an imported master-catalog CSV field) become a live formula for whoever
opens the exported .xlsx - the classic CSV/Excel formula injection (OWASP).
A string starting with =, +, -, @, or a tab/CR gets a defensive leading
apostrophe; everything else (numbers, None, booleans, ordinary text) is
untouched."""
from __future__ import annotations

from pdf_document_intelligence.export.excel import _safe_cell, _safe_row


def test_formula_trigger_characters_get_neutralized():
    for trigger in ("=", "+", "-", "@"):
        malicious = f"{trigger}HYPERLINK(\"http://evil.example\",\"click me\")"
        result = _safe_cell(malicious)
        assert result == "'" + malicious
        assert not result.startswith(trigger)


def test_ordinary_text_is_untouched():
    assert _safe_cell("เพอร์ริเย่ต์ น้ำแร่ 1500 มล.") == "เพอร์ริเย่ต์ น้ำแร่ 1500 มล."
    assert _safe_cell("100-PACK") == "100-PACK"  # hyphen not at position 0


def test_non_string_values_pass_through_unchanged():
    assert _safe_cell(42) == 42
    assert _safe_cell(None) is None
    assert _safe_cell(3.14) == 3.14


def test_safe_row_maps_over_a_whole_row():
    row = ["ok", "=cmd|'/C calc'!A0", 5, None]
    result = _safe_row(row)
    assert result[0] == "ok"
    assert result[1] == "'=cmd|'/C calc'!A0"
    assert result[2] == 5
    assert result[3] is None
