"""Errors raised by Repository's atomic write paths.

Lives here (not in api/review.py, where RowConflictError originally lived)
because repository.py must be able to raise it directly from inside its
conditional UPDATE - and repository.py cannot import api/review.py without
creating a cycle (review.py already imports repository.py).
"""
from __future__ import annotations


class RowConflictError(Exception):
    """The row's current `updated_at` no longer matches the caller's
    `expected_updated_at` - someone else's write landed first. Raised from
    inside the same write transaction as the conditional UPDATE that
    detected it (PR12 fix: the previous SELECT-then-compare-then-UPDATE
    left a window between the check and the write where two concurrent
    callers could both pass the check), so this is always based on the
    row's true current state, not a stale read. Carries that current state
    so the caller can hand it back to the client instead of just saying
    "conflict" with nothing to act on."""

    def __init__(self, current_row: dict) -> None:
        self.current_row = current_row
        super().__init__("This product row was changed by someone else since it was loaded.")


class RowNotFoundError(Exception):
    """The row doesn't exist, or is soft-deleted (deleted_at is set) - a
    conditional UPDATE's WHERE clause never matches it. Distinct from
    RowConflictError so the caller can return 404 rather than 412: a
    deleted row was never a version conflict, it's just gone."""

    def __init__(self, row_id: str) -> None:
        self.row_id = row_id
        super().__init__(f"product row {row_id} not found")
