"""ExportService: 4-sheet Excel export (Data / Validation Issues / Document
Summary / Audit). Code fields are written with an explicit text number
format so leading zeros survive (proposal §23/§56); numeric fields keep
their native type so Excel can sum them.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from pdf_document_intelligence.models.document import DocumentResult
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS

_HEADER_FONT = Font(bold=True)


def _write_header(ws: Worksheet, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT


def _write_data_sheet(ws: Worksheet, results: list[DocumentResult], multi: bool = False) -> None:
    headers = (["source_file"] if multi else []) + [
        "department", *[c.canonical_name for c in COLUMNS], "row_confidence", "review_required"
    ]
    _write_header(ws, headers)
    for result in results:
        for table in result.tables:
            for row in table.rows:
                values: list[object] = [result.filename] if multi else []
                values.append(table.name)
                for col in COLUMNS:
                    fv = row.fields.get(col.canonical_name)
                    values.append(fv.value if fv else None)
                review = any(f.review_required for f in row.fields.values())
                values.append(row.confidence_band)
                values.append("YES" if review else "")
                ws.append(values)
    # Code columns (dn_no, do_no, order_no, pallet, lot, article, barcode)
    # are written as text so Excel never strips leading zeros.
    offset = 2 + (1 if multi else 0)  # 1-indexed, + optional source_file col, + department col
    code_col_indices = [i + offset for i, c in enumerate(COLUMNS) if c.field_type == "code"]
    for col_idx in code_col_indices:
        for row_idx in range(2, ws.max_row + 1):
            ws.cell(row=row_idx, column=col_idx).number_format = "@"


def _write_issues_sheet(ws: Worksheet, results: list[DocumentResult], multi: bool = False) -> None:
    headers = (["source_file"] if multi else []) + ["severity", "code", "table", "row_index", "field", "message"]
    _write_header(ws, headers)
    for result in results:
        for issue in [*result.validation.errors, *result.validation.warnings]:
            row = [result.filename] if multi else []
            row += [issue.severity, issue.code, issue.table, issue.row_index, issue.field, issue.message]
            ws.append(row)


def _write_summary_sheet(ws: Worksheet, results: list[DocumentResult]) -> None:
    _write_header(
        ws,
        [
            "filename", "pages", "document_type", "tables", "total_rows", "low_confidence_rows",
            "rows_needing_review", "validation_errors", "validation_warnings", "reconciliation_status",
            "document_confidence_pct", "status", "engine_version", "parser_version", "template_version",
        ],
    )
    for result in results:
        total_rows = sum(len(t.rows) for t in result.tables)
        low_conf_rows = sum(1 for t in result.tables for r in t.rows if r.confidence_band == "LOW")
        rows_needing_review = sum(
            1 for t in result.tables for r in t.rows if any(f.review_required for f in r.fields.values())
        )
        ws.append(
            [
                result.filename, result.pages, result.document_type, len(result.tables), total_rows,
                low_conf_rows, rows_needing_review, len(result.validation.errors), len(result.validation.warnings),
                "PASSED" if result.validation.reconciled else "FAILED", round(result.confidence, 2), result.status,
                result.engine_version, result.parser_version, result.template_version,
            ]
        )


def _write_audit_sheet(ws: Worksheet, results: list[DocumentResult], multi: bool = False) -> None:
    headers = (["source_file"] if multi else []) + ["step", "detail", "timestamp", "duration_ms"]
    _write_header(ws, headers)
    for result in results:
        for entry in result.processing_log:
            row = [result.filename] if multi else []
            row += [entry.step, entry.detail, entry.timestamp.isoformat(), entry.duration_ms]
            ws.append(row)


def export_to_excel(result: DocumentResult, output_path: Path) -> Path:
    return export_many_to_excel([result], output_path)


def export_many_to_excel(results: list[DocumentResult], output_path: Path) -> Path:
    multi = len(results) > 1
    wb = Workbook()
    data_ws = wb.active
    data_ws.title = "Extracted Data"
    _write_data_sheet(data_ws, results, multi=multi)

    _write_issues_sheet(wb.create_sheet("Validation Issues"), results, multi=multi)
    _write_summary_sheet(wb.create_sheet("Document Summary"), results)
    _write_audit_sheet(wb.create_sheet("Audit"), results, multi=multi)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path
