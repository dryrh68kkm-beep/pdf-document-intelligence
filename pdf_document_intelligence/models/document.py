"""Core data model: BoundingBox -> FieldValue -> TableRow -> ExtractedTable -> DocumentResult.

Every value that reaches a human or an export must be traceable back to a
page + bounding box (evidence-first architecture, proposal §61).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FieldType = Literal[
    "string", "integer", "decimal", "currency", "percentage",
    "date", "time", "datetime", "code", "boolean",
]
FieldSource = Literal["pdf_text", "ocr", "cross_validated"]
ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]
DocumentStatus = Literal["AUTO_APPROVED", "REVIEW_RECOMMENDED", "MANUAL_REVIEW_REQUIRED"]


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float
    page: int


class CorrectionEvent(BaseModel):
    original_value: str
    corrected_value: str
    user: str
    timestamp: datetime
    reason: str | None = None


class FieldValue(BaseModel):
    name: str
    raw_value: str
    value: str | int | float | None
    type: FieldType
    bbox: BoundingBox
    source: FieldSource
    confidence: float = Field(ge=0.0, le=1.0)
    validation_flags: list[str] = Field(default_factory=list)
    review_required: bool = False
    correction: CorrectionEvent | None = None
    # Cross-validation evidence (proposal §2/§14): populated only when OCR
    # was actually attempted for this field. `raw_value` above is always the
    # PDF text-layer reading and is never overwritten by OCR — `value` is
    # the pipeline's selected final reading, and `source` says which one won.
    ocr_raw_value: str | None = None
    ocr_confidence: float | None = None


class TableRow(BaseModel):
    row_index: int
    fields: dict[str, FieldValue]
    confidence_band: ConfidenceBand


class ExtractedTable(BaseModel):
    name: str
    page_start: int
    page_end: int
    header: list[str]
    rows: list[TableRow]
    source_pages: list[int]


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"]
    table: str | None = None
    row_index: int | None = None
    field: str | None = None


class ValidationSummary(BaseModel):
    reconciled: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class ProcessingLogEntry(BaseModel):
    step: str
    detail: str
    timestamp: datetime
    duration_ms: float | None = None


class DocumentResult(BaseModel):
    id: str
    filename: str
    pages: int
    document_type: str | None
    engine_version: str
    ocr_engine_version: str
    parser_version: str
    template_version: str | None
    confidence: float
    status: DocumentStatus
    tables: list[ExtractedTable] = Field(default_factory=list)
    fields: list[FieldValue] = Field(default_factory=list)
    validation: ValidationSummary
    processing_log: list[ProcessingLogEntry] = Field(default_factory=list)
