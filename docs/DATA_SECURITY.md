# Data Security Policy

This repository contains source code only. Operational/company documents and master data must not be committed.

## Never commit

- Real PDF documents, scans, packing lists, invoices, or exported reports.
- Company product/master catalogs or hierarchy exports.
- Expected-output JSON/CSV files generated from real documents.
- Runtime uploads, SQLite databases, backups, or exported spreadsheets containing operational data.
- Credentials, API keys, tokens, or `.env` files.

## Testing policy

Regression fixtures must be synthetic or irreversibly redacted. PDF fixtures are generated at test runtime inside temporary directories. Fictional identifiers, barcodes, quantities, names, stores, routes, and departments must be used.

## Production data

External master data may be supplied locally using `PDF_INTELLIGENCE_MASTER_CATALOG`. Missing master data is a supported state: the application must fall back to PDF/OCR evidence and human review instead of guessing.

## Incident response

If sensitive data is accidentally committed:

1. Stop feature work and prevent additional pushes of the data.
2. Remove the file from the current branch and add an ignore/CI guard.
3. Replace affected tests with synthetic/redacted fixtures.
4. Treat the Git history as still containing the data until history is rewritten and old refs/caches are cleaned.
5. Rotate any credentials if secrets were exposed.

History rewriting is an administrative operation and must be performed deliberately because it changes commit SHAs and requires collaborators/clones to resynchronize.
