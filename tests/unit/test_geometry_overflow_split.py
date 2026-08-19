"""Unit tests for geometry.split_glued_code_suffix - the character-class
split used to recover a Department name and an Article code that the
BPDC template's source PDF renders at overlapping X positions (see
tables/reconstruct_bpdc.py's _split_department_article_overflow and
tests/integration/test_golden_regression_bpdc.py for the real traced
example: "STATIONERY & EDUTAINMEN1T02313106-00-001").
"""
from __future__ import annotations

from pdf_document_intelligence.tables.geometry import ARTICLE_RE, split_glued_code_suffix


def test_splits_real_traced_example():
    text = "STATIONERY & EDUTAINMEN1T02313106-00-001"
    result = split_glued_code_suffix(text, ARTICLE_RE)
    assert result == ("STATIONERY & EDUTAINMENT", "102313106-00-001")


def test_splits_second_real_traced_example():
    text = "STATIONERY & EDUTAINMEN1T03219960-00-000"
    result = split_glued_code_suffix(text, ARTICLE_RE)
    assert result == ("STATIONERY & EDUTAINMENT", "103219960-00-000")


def test_ordinary_department_name_is_left_alone():
    """No digit/hyphen stream at all -> nothing to split; must return None
    so the caller never touches a normal department name."""
    assert split_glued_code_suffix("BEVERAGE", ARTICLE_RE) is None


def test_digit_stream_not_shaped_like_an_article_code_is_rejected():
    """A department name that happens to contain a short number (not the
    9-2-3 digit article shape) must never be guessed into a split -
    "never guess" applies here as much as anywhere else in the pipeline."""
    assert split_glued_code_suffix("ZONE 5 GROCERY", ARTICLE_RE) is None


def test_empty_label_after_split_is_rejected():
    """A pure article code with no surrounding letters at all is not a
    glued department+article case - nothing to recover a label from."""
    assert split_glued_code_suffix("102313106-00-001", ARTICLE_RE) is None
