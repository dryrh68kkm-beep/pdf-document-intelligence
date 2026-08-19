"""ExportService: 4-sheet Excel export (Data / Validation Issues / Document
Summary / Audit). Code fields are written with an explicit text number
format so leading zeros survive (proposal §23/§56); numeric fields keep
their native type so Excel can sum them.

Works off the same dict shape `api/serialize.py` hands the frontend
(`document_detail_json`), not the raw pipeline `DocumentResult` - a row's
`fields[...]["value"]` is already the *current* value (post-correction),
so an edited quantity/name shows up in the export without a second code
path re-deriving it.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS

_HEADER_FONT = Font(bold=True)


def _write_header(ws: Worksheet, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT


def _write_data_sheet(ws: Worksheet, docs: list[dict], multi: bool = False) -> None:
    headers = (["source_file"] if multi else []) + [
        "department", *[c.canonical_name for c in COLUMNS],
        "row_confidence", "review_required", "corrected", "suspected_non_product", "non_product_reasons",
    ]
    _write_header(ws, headers)
    for doc in docs:
        for product in doc.get("products", []):
            values: list[object] = [doc["filename"]] if multi else []
            values.append(product["department"])
            row_corrected = False
            for col in COLUMNS:
                fv = product["fields"].get(col.canonical_name)
                values.append(fv["value"] if fv else None)
                if fv and fv.get("corrected"):
                    row_corrected = True
            values.append(product["band"])
            values.append("YES" if product["reviewRequired"] else "")
            values.append("YES" if row_corrected else "")
            values.append("YES" if product["suspectedNonProduct"] else "")
            values.append(", ".join(product.get("nonProductReasons", [])))
            ws.append(values)
    offset = 2 + (1 if multi else 0)
    code_col_indices = [i + offset for i, c in enumerate(COLUMNS) if c.field_type == "code"]
    for col_idx in code_col_indices:
        for row_idx in range(2, ws.max_row + 1):
            ws.cell(row=row_idx, column=col_idx).number_format = "@"


def _write_issues_sheet(ws: Worksheet, docs: list[dict], multi: bool = False) -> None:
    headers = (["source_file"] if multi else []) + ["severity", "code", "table", "row_index", "field", "message"]
    _write_header(ws, headers)
    for doc in docs:
        for issue in doc.get("validationIssues", []):
            row = [doc["filename"]] if multi else []
            row += [issue["severity"], issue["code"], issue["table"], issue["rowIndex"], issue["field"], issue["message"]]
            ws.append(row)


def _write_summary_sheet(ws: Worksheet, docs: list[dict]) -> None:
    _write_header(
        ws,
        [
            "filename", "pages", "total_rows", "low_confidence_rows",
            "rows_needing_review", "validation_errors", "validation_warnings", "reconciliation_status",
            "document_confidence_pct", "status", "engine_version", "template_version",
        ],
    )
    for doc in docs:
        products = doc.get("products", [])
        total_rows = len(products)
        low_conf_rows = sum(1 for p in products if p["band"] == "LOW")
        rows_needing_review = sum(1 for p in products if p["reviewRequired"])
        issues = doc.get("validationIssues", [])
        ws.append(
            [
                doc["filename"], doc.get("pages"), total_rows, low_conf_rows, rows_needing_review,
                sum(1 for i in issues if i["severity"] == "error"),
                sum(1 for i in issues if i["severity"] == "warning"),
                "PASSED" if doc.get("reconciled") else "FAILED",
                doc.get("confidence"), doc.get("status_document"),
                doc.get("engineVersion"), doc.get("templateVersion"),
            ]
        )


def _write_audit_sheet(ws: Worksheet, docs: list[dict], multi: bool = False) -> None:
    headers = (["source_file"] if multi else []) + ["step", "detail", "timestamp", "duration_ms"]
    _write_header(ws, headers)
    for doc in docs:
        for entry in doc.get("processingLog", []):
            row = [doc["filename"]] if multi else []
            row += [entry["step"], entry["detail"], entry.get("timestamp"), entry.get("durationMs")]
            ws.append(row)


def export_to_excel(doc: dict, output_path: Path) -> Path:
    return export_many_to_excel([doc], output_path)


def export_many_to_excel(docs: list[dict], output_path: Path) -> Path:
    multi = len(docs) > 1
    wb = Workbook()
    data_ws = wb.active
    data_ws.title = "Extracted Data"
    _write_data_sheet(data_ws, docs, multi=multi)

    _write_issues_sheet(wb.create_sheet("Validation Issues"), docs, multi=multi)
    _write_summary_sheet(wb.create_sheet("Document Summary"), docs)
    _write_audit_sheet(wb.create_sheet("Audit"), docs, multi=multi)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path
