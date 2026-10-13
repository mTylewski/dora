"""Local OCR for pages without a text layer (Tesseract, language `pol`).

Runs entirely on the server. Requires the `tesseract` binary with Polish
language data (Debian/Ubuntu: apt install tesseract-ocr tesseract-ocr-pol)
and the Python packages `pytesseract` and `pypdfium2`.
"""

from __future__ import annotations

from pathlib import Path

DPI = 300


def tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return "pol" in pytesseract.get_languages(config="")
    except Exception:  # binary missing or misconfigured
        return False


def ocr_page(pdf_path: Path, page_number: int) -> str:  # pragma: no cover - needs tesseract binary
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[page_number - 1]
        image = page.render(scale=DPI / 72).to_pil()
    finally:
        pdf.close()
    return pytesseract.image_to_string(image, lang="pol")
