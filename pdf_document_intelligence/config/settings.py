"""All tunable thresholds/weights/limits for the pipeline.

Nothing here is hard-coded into pipeline logic — every module that needs a
threshold reads it from a `Settings` instance instead. This is deliberate
per the architecture proposal: confidence bands, tolerances, and limits
must stay configuration, not magic numbers buried in code.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PDI_", env_file=".env", extra="ignore")

    # --- File / page limits ---
    max_file_size_bytes: int = 200 * 1024 * 1024
    max_pages: int = 500

    # --- Text-layer quality thresholds (0.0-1.0) ---
    min_printable_char_ratio: float = 0.85
    min_thai_valid_char_ratio: float = 0.90
    max_replacement_char_ratio: float = 0.01
    # Minimum fraction of Thai-block characters that must be combining
    # vowels/tone marks in a Thai-heavy passage, or the text layer is
    # treated as silently dropping glyphs (see extract/text.py).
    min_thai_combining_density: float = 0.08
    # Below this composite text-quality score, a page/field is treated as
    # "text layer unreliable" and flagged for OCR cross-check (or, when OCR
    # is unavailable/out of scope, flagged NEEDS_REVIEW rather than trusted).
    text_quality_ocr_threshold: float = 0.90

    # --- OCR confidence bands ---
    ocr_confidence_high: float = 0.95
    ocr_confidence_medium: float = 0.85

    # --- Reconciliation tolerance (currency/quantity sums) ---
    reconciliation_abs_tolerance: float = 0.02

    # --- Confidence weights (must sum to 1.0; validated in ConfidenceEngine) ---
    weight_extraction: float = 0.30
    weight_ocr: float = 0.15
    weight_layout: float = 0.15
    weight_schema: float = 0.15
    weight_validation: float = 0.25

    # --- Document-level status thresholds (percentages, 0-100) ---
    auto_approved_threshold: float = 98.0
    review_recommended_threshold: float = 90.0

    # --- Critical-field stricter threshold ---
    # Names must match a document type's actual canonical field names (see
    # templates/*.py ColumnSpec) or this list silently matches nothing and
    # the extra penalty below never applies to any field.
    critical_field_min_confidence: float = 0.95
    critical_fields: tuple[str, ...] = ("barcode", "weight_qty", "pu_qty", "sku_qty")

    engine_version: str = "0.1.0"
    parser_version: str = "0.1.0"
    ocr_engine_version: str = "unset"

    # --- Auto PDF Folder Import (data/inbox) ---
    # A user drops a PDF into data/inbox instead of using the Add Files
    # button; the app notices it, dedupes it against `documents` the same
    # way a manual upload does, and feeds it through the same pipeline.
    # inbox_enabled=False (still true by default) is an escape hatch for a
    # deployment that wants the Add Files button only, with no filesystem
    # watching at all.
    inbox_enabled: bool = True
    inbox_scan_interval_seconds: float = 7.0

    # --- Viewer/Admin permission gate (PR13) ---
    # A single shared passphrase, not a user-account system - this app has
    # no login. Empty (the default) means the gate is off entirely: every
    # deployment that hasn't explicitly opted in keeps working exactly as
    # before this PR, with unrestricted access. An operator sets
    # PDI_ADMIN_PASSPHRASE to turn every mutating endpoint Admin-only,
    # leaving read endpoints open to anyone on the LAN as a Viewer.
    admin_passphrase: str = ""


def get_settings() -> Settings:
    return Settings()
