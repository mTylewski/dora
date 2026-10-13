"""Step 0: text from PDF, page by page.

Pages without a usable text layer are handed to local OCR (pipeline.ocr).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pdfplumber

from pipeline.documents import Document

# A page with fewer non-whitespace characters than this is treated as a scan.
MIN_TEXT_CHARS = 40

OcrFn = Callable[[Path, int], str]  # (pdf path, 1-based page) -> text


def needs_ocr(text: str | None) -> bool:
    return text is None or len("".join(text.split())) < MIN_TEXT_CHARS


PageProgress = Callable[[int, int, bool], None]  # (page, pages in document, OCR used)


def read_pdf(path: Path, doc_id: str, ocr: OcrFn | None = None, on_page: PageProgress | None = None) -> Document:
    pages: list[str] = []
    ocr_pages: list[int] = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=False) or ""
            if needs_ocr(text) and ocr is not None:
                text = ocr(path, number)
                ocr_pages.append(number)
            pages.append(text)
            if on_page:
                on_page(number, total, number in ocr_pages)
    return Document(id=doc_id, filename=path.name, pages=pages, ocr_pages=ocr_pages)


def read_pdfs(paths: list[Path], ocr: OcrFn | None = None,
              on_page: Callable[[int, int, int, int, bool], None] | None = None) -> list[Document]:
    """on_page(document no., documents, page, pages in document, OCR used)"""
    docs = []
    for i, p in enumerate(paths, start=1):
        callback = (lambda page, total, used, i=i: on_page(i, len(paths), page, total, used)) if on_page else None
        docs.append(read_pdf(p, f"doc_{i}", ocr, callback))
    return docs
