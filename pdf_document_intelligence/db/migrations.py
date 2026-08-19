"""Schema migrations, applied in order against `schema_version`.

Deliberately not `CREATE TABLE IF NOT EXISTS` forever (spec requirement):
each migration is a numbered, one-way step recorded in `schema_version` so
a future release can add migration 2, 3, ... without losing existing data.
Plain sqlite3 (stdlib), no ORM - this is a single-writer desktop-local app.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

Migration = Callable[[sqlite3.Connection], None]


def _migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE documents (
            id              TEXT PRIMARY KEY,
            sha256          TEXT NOT NULL,
            filename        TEXT NOT NULL,
            file_size       INTEGER NOT NULL,
            page_count      INTEGER,
            status          TEXT NOT NULL DEFAULT 'processing',
            error           TEXT,
            progress_stage  TEXT NOT NULL DEFAULT 'queued',
            progress_current INTEGER NOT NULL DEFAULT 0,
            progress_total  INTEGER NOT NULL DEFAULT 0,
            meta_json       TEXT,
            uploaded_at     TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            deleted_at      TEXT
        );
        CREATE UNIQUE INDEX idx_documents_sha256_active
            ON documents(sha256) WHERE deleted_at IS NULL;
        CREATE INDEX idx_documents_status ON documents(status);

        CREATE TABLE product_rows (
            id                      TEXT PRIMARY KEY,
            document_id             TEXT NOT NULL REFERENCES documents(id),
            source_page             INTEGER,
            row_index               INTEGER NOT NULL,
            department              TEXT,
            barcode                 TEXT,
            article_code            TEXT,
            identity_code           TEXT,
            raw_product_name        TEXT,
            ocr_product_name        TEXT,
            resolved_product_name   TEXT,
            weight_qty              REAL,
            pu_qty                  REAL,
            sku_qty                 REAL,
            unit                    TEXT,
            unit_price              REAL,
            amount                  REAL,
            confidence              REAL,
            confidence_band         TEXT,
            resolution_status       TEXT NOT NULL DEFAULT 'OCR',
            review_required         INTEGER NOT NULL DEFAULT 0,
            review_reasons          TEXT,
            suspected_non_product   INTEGER NOT NULL DEFAULT 0,
            non_product_reasons     TEXT,
            fields_json             TEXT NOT NULL,
            corrected_fields_json   TEXT NOT NULL DEFAULT '[]',
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            deleted_at              TEXT
        );
        CREATE INDEX idx_rows_document ON product_rows(document_id);
        CREATE INDEX idx_rows_barcode ON product_rows(barcode);
        CREATE INDEX idx_rows_article ON product_rows(article_code);
        CREATE INDEX idx_rows_identity ON product_rows(identity_code);
        CREATE INDEX idx_rows_department ON product_rows(department);
        CREATE INDEX idx_rows_review ON product_rows(review_required);

        CREATE TABLE corrections (
            id                  TEXT PRIMARY KEY,
            product_row_id      TEXT NOT NULL REFERENCES product_rows(id),
            field_name          TEXT NOT NULL,
            old_value           TEXT,
            new_value           TEXT,
            reason              TEXT,
            source              TEXT NOT NULL DEFAULT 'LOCAL_USER',
            undo_of_id          TEXT REFERENCES corrections(id),
            created_at          TEXT NOT NULL
        );
        CREATE INDEX idx_corrections_row ON corrections(product_row_id);

        CREATE TABLE local_product_master (
            id                  TEXT PRIMARY KEY,
            barcode             TEXT NOT NULL UNIQUE,
            article_code        TEXT,
            product_name        TEXT NOT NULL,
            department          TEXT,
            unit                TEXT,
            source_document_id  TEXT REFERENCES documents(id),
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );
        CREATE INDEX idx_local_master_article ON local_product_master(article_code);

        CREATE TABLE schema_version (
            version     INTEGER NOT NULL,
            applied_at  TEXT NOT NULL
        );
        """
    )


MIGRATIONS: list[Migration] = [
    _migration_001_initial_schema,
]


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not row:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def run_migrations(conn: sqlite3.Connection) -> int:
    """Applies any migrations newer than the DB's current schema_version.
    Returns the resulting schema version."""
    version = current_version(conn)
    with conn:
        for idx, migration in enumerate(MIGRATIONS, start=1):
            if idx <= version:
                continue
            migration(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (idx,),
            )
            version = idx
    return version


SCHEMA_VERSION = len(MIGRATIONS)
