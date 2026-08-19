"""Shared template definition types, used by every registered document
template (packing_list_bigc.py, packing_list_bpdc.py, ...)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    canonical_name: str
    header_tokens: tuple[str, ...]
    field_type: str  # FieldType from models.document
    is_group_key: bool = False  # forward-filled: blank cell inherits previous row's value
    required: bool = True  # blank is legitimate (not MISSING_FIELD) when False
