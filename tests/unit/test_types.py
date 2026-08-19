import pytest

from pdf_document_intelligence.normalize.types import TypeParseError, normalize_digits, parse_integer, parse_number


def test_normalize_digits():
    assert normalize_digits("๑๒๓") == "123"
    assert normalize_digits("abc") == "abc"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234", 1234.0),
        ("1,234.50", 1234.50),
        ("-1,234.50", -1234.50),
        ("(1,234.50)", -1234.50),
        ("฿1,234", 1234.0),
        ("0.360", 0.36),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == pytest.approx(expected)


def test_parse_number_rejects_ambiguous_decimal_separators():
    with pytest.raises(TypeParseError):
        parse_number("1.234,50")


def test_parse_integer_requires_whole_number():
    assert parse_integer("12") == 12
    with pytest.raises(TypeParseError):
        parse_integer("12.5")
