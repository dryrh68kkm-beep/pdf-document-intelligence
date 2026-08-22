"""Explainable document-quality scoring built from existing extraction evidence.

This is intentionally deterministic and non-AI: it summarizes signals the
pipeline already produces (field confidence, identifier validation, exact
master matches, validation issues, and row review flags) into a 0-100 score
with a component breakdown that can be shown in the UI.
"""
from __future__ import annotations

from pdf_document_intelligence.models.document import ExtractedTable, QualitySummary, ValidationSummary


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_quality(tables: list[ExtractedTable], validation: ValidationSummary) -> QualitySummary:
    rows = [row for table in tables for row in table.rows]
    fields = [field for row in rows for field in row.fields.values()]
    if not rows or not fields:
        return QualitySummary(
            score=0.0,
            band="HIGH_RISK",
            breakdown={"extraction": 0.0, "identity": 0.0, "master": 0.0, "validation": 0.0, "review": 0.0},
            row_count=0,
            verified_rows=0,
            review_rows=0,
            error_count=len(validation.errors),
            warning_count=len(validation.warnings),
            master_matched_rows=0,
        )

    extraction = 100.0 * sum(field.confidence for field in fields) / len(fields)

    identity_fields = [
        field for row in rows for name, field in row.fields.items() if name in {"article", "barcode"}
    ]
    valid_identity = sum(
        1
        for field in identity_fields
        if field.value is not None
        and "MISSING_FIELD" not in field.validation_flags
        and "INVALID_ARTICLE_FORMAT" not in field.validation_flags
        and "INVALID_BARCODE_FORMAT" not in field.validation_flags
    )
    identity = 100.0 * valid_identity / len(identity_fields) if identity_fields else 0.0

    master_matched = sum(
        1 for row in rows if row.fields.get("name") and row.fields["name"].source == "master_catalog"
    )
    master = 100.0 * master_matched / len(rows)

    validation_score = _clamp(100.0 - 20.0 * len(validation.errors) - 5.0 * len(validation.warnings))

    review_rows = sum(1 for row in rows if any(field.review_required for field in row.fields.values()))
    verified_rows = len(rows) - review_rows
    review = 100.0 * verified_rows / len(rows)

    breakdown = {
        "extraction": round(extraction, 2),
        "identity": round(identity, 2),
        "master": round(master, 2),
        "validation": round(validation_score, 2),
        "review": round(review, 2),
    }
    score = round(
        extraction * 0.40
        + identity * 0.20
        + master * 0.15
        + validation_score * 0.15
        + review * 0.10,
        2,
    )

    if score >= 95:
        band = "VERIFIED"
    elif score >= 80:
        band = "GOOD"
    elif score >= 60:
        band = "NEED_REVIEW"
    else:
        band = "HIGH_RISK"

    return QualitySummary(
        score=score,
        band=band,
        breakdown=breakdown,
        row_count=len(rows),
        verified_rows=verified_rows,
        review_rows=review_rows,
        error_count=len(validation.errors),
        warning_count=len(validation.warnings),
        master_matched_rows=master_matched,
    )
