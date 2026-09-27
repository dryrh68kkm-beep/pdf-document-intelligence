"""Shared helper for parsing JSON stored in a SQLite TEXT column.

Live reports found this same bug independently in four separate places
(divisions.py's _reconciliation, serialize.py's product_row_json/
document_summary_json, and aggregate.py's _json_list) before this module
existed: a single row's corrupted stored JSON (fields_json,
review_reasons, non_product_reasons, meta_json, ...) crashed whatever
endpoint happened to read it with an unguarded json.loads() - and because
several of those endpoints (`/api/products`, `/api/documents`, `/api/state`)
aggregate over every row/document in the whole app in one pass, one bad
row took every other document's data down with it, not just its own.

Every call site in this codebase that parses a stored JSON column should
use this instead of a bare json.loads() - never duplicate this fix a
fifth time.
"""
from __future__ import annotations

import json


def safe_json_loads(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
