"""ConfidenceEngine: composite document-level confidence + status.

Field/row confidence is already computed upstream (tables/fields.py). This
module rolls those up into one document score plus a status band, and is
where "how much do the numbers matter vs. how much does OCR matter"
weighting (proposal §28) would apply once OCR/layout/schema sub-scores
exist — for this OCR-deferred slice, extraction+validation dominate.
"""
from __future__ import annotations

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.models.document import DocumentStatus, ExtractedTable, ValidationSummary


def score_document(
    tables: list[ExtractedTable],
    validation: ValidationSummary,
    settings: Settings,
) -> tuple[float, DocumentStatus]:
    all_fields = [f for t in tables for row in t.rows for f in row.fields.values()]
    if not all_fields:
        return 0.0, "MANUAL_REVIEW_REQUIRED"

    extraction_score = sum(f.confidence for f in all_fields) / len(all_fields)

    critical_fields = [f for f in all_fields if f.name in settings.critical_fields]
    critical_penalty = 0.0
    if critical_fields:
        below_threshold = [f for f in critical_fields if f.confidence < settings.critical_field_min_confidence]
        critical_penalty = len(below_threshold) / len(critical_fields)

    validation_score = 1.0
    if validation.errors:
        validation_score = max(0.0, 1.0 - 0.15 * len(validation.errors))
    elif validation.warnings:
        validation_score = max(0.5, 1.0 - 0.05 * len(validation.warnings))

    composite = (
        extraction_score * (settings.weight_extraction + settings.weight_ocr + settings.weight_layout + settings.weight_schema)
        + validation_score * settings.weight_validation
    )
    composite = composite * (1 - 0.5 * critical_penalty)
    composite_pct = max(0.0, min(100.0, composite * 100))

    any_review_required = any(f.review_required for f in all_fields)

    if composite_pct >= settings.auto_approved_threshold and not validation.errors and not any_review_required:
        status: DocumentStatus = "AUTO_APPROVED"
    elif composite_pct >= settings.review_recommended_threshold and not validation.errors:
        status = "REVIEW_RECOMMENDED"
    else:
        status = "MANUAL_REVIEW_REQUIRED"

    return composite_pct, status
