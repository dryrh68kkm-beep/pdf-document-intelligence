"""PDFLoader: open + preflight every PDF before any content is trusted.

Untrusted input (proposal §54): we never hand pdfplumber/pypdf a file we
haven't first sanity-checked with pikepdf (qpdf bindings), which is far
more robust against malformed/truncated/decompression-bomb-shaped PDFs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from pdf_document_intelligence.config.settings import Settings

PDF_MAGIC = b"%PDF-"


class PreflightError(Exception):
    """Raised for a file that must not proceed past preflight (e.g. wrong
    signature, too large, encrypted without a usable password)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _without_path(exc: Exception, path: Path) -> str:
    return str(exc).replace(str(path), path.name)


@dataclass
class PagePreflight:
    page_number: int
    width: float
    height: float
    rotation: int


@dataclass
class DocumentPreflight:
    filename: str
    file_size_bytes: int
    pdf_version: str
    page_count: int
    is_encrypted: bool
    pages: list[PagePreflight] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_preflight(path: Path, settings: Settings) -> DocumentPreflight:
    file_size = path.stat().st_size
    if file_size == 0:
        raise PreflightError("PDF_CORRUPTED", "File is empty")
    if file_size > settings.max_file_size_bytes:
        raise PreflightError(
            "FILE_TOO_LARGE",
            f"{file_size} bytes exceeds max_file_size_bytes={settings.max_file_size_bytes}",
        )

    with path.open("rb") as fh:
        header = fh.read(8)
    if not header.startswith(PDF_MAGIC):
        raise PreflightError("NOT_A_PDF", f"File signature {header!r} is not a PDF")

    try:
        pdf = pikepdf.open(str(path))
    except pikepdf.PasswordError as exc:
        # pikepdf's own exception message is prefixed with the absolute
        # path it opened (e.g. "/data/pdfs/<uuid>.pdf: ..."); that path
        # is server-internal storage layout, not something a client-visible
        # error message should ever carry - substitute the bare filename.
        raise PreflightError("PDF_PASSWORD_REQUIRED", _without_path(exc, path)) from exc
    except pikepdf.PdfError as exc:
        raise PreflightError("PDF_CORRUPTED", _without_path(exc, path)) from exc

    warnings: list[str] = []
    try:
        page_count = len(pdf.pages)
        if page_count == 0:
            raise PreflightError("PDF_CORRUPTED", "PDF has zero pages")
        if page_count > settings.max_pages:
            raise PreflightError(
                "TOO_MANY_PAGES", f"{page_count} pages exceeds max_pages={settings.max_pages}"
            )

        pages: list[PagePreflight] = []
        for i, page in enumerate(pdf.pages):
            try:
                mediabox = page.mediabox
                width = float(mediabox[2]) - float(mediabox[0])
                height = float(mediabox[3]) - float(mediabox[1])
            except Exception:
                warnings.append(f"page {i + 1}: could not read mediabox, defaulting to 0x0")
                width = height = 0.0
            rotation = int(page.get("/Rotate", 0)) % 360
            pages.append(PagePreflight(page_number=i + 1, width=width, height=height, rotation=rotation))

        pdf_version = pdf.pdf_version

        return DocumentPreflight(
            filename=path.name,
            file_size_bytes=file_size,
            pdf_version=str(pdf_version),
            page_count=page_count,
            is_encrypted=pdf.is_encrypted,
            pages=pages,
            warnings=warnings,
        )
    finally:
        pdf.close()
