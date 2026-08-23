from types import SimpleNamespace

from pdf_document_intelligence.extract.document_date import extract_document_date


def _document(*pages: str):
    return SimpleNamespace(pages=[SimpleNamespace(page_number=i + 1, raw_text=text) for i, text in enumerate(pages)])


def test_extracts_explicit_english_document_date():
    match = extract_document_date(_document("Packing List\nDocument Date: 2026-08-19\nMFG Date: 2026-07-01"))

    assert match is not None
    assert match.value.isoformat() == "2026-08-19"
    assert match.raw_value == "2026-08-19"
    assert match.label == "Document Date"
    assert match.page == 1


def test_converts_thai_buddhist_era_date():
    match = extract_document_date(_document("วันที่เอกสาร : 19/08/2569"))

    assert match is not None
    assert match.value.isoformat() == "2026-08-19"
    assert match.label == "วันที่เอกสาร"


def test_never_uses_mfg_or_expiry_as_document_date():
    match = extract_document_date(
        _document("MFG Date: 01/08/2026\nExpiry Date: 01/08/2027\nLot: 190826")
    )

    assert match is None


def test_prefers_document_date_over_a_later_generic_date():
    match = extract_document_date(
        _document("Date: 20/08/2026\nDocument Date: 19/08/2026")
    )

    assert match is not None
    assert match.value.isoformat() == "2026-08-19"
    assert match.label == "Document Date"


def test_falls_back_to_packing_list_print_timestamp_when_no_other_label_present():
    """Real BPDC packing lists (user-reported: document date not showing in
    the app at all) carry no explicit "Document Date"/"วันที่เอกสาร" label
    anywhere - the only date on the page is the print timestamp printed
    directly under the report title, repeated on every page:
    "Page 1 of 23\\n19/08/2026 04:57:47\\nPacking List\\n19/08/2026 04:57\\n..."."""
    match = extract_document_date(
        _document("Page 1 of 23\n19/08/2026 04:57:47\nPacking List\n19/08/2026 04:57\n00 : 91101 BPDC")
    )

    assert match is not None
    assert match.value.isoformat() == "2026-08-19"
    assert match.label == "Packing List"


def test_packing_list_fallback_never_overrides_an_explicit_label():
    match = extract_document_date(
        _document("Packing List\n01/01/2020\nDocument Date: 19/08/2026")
    )

    assert match is not None
    assert match.value.isoformat() == "2026-08-19"
    assert match.label == "Document Date"
