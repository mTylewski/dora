"""Case documents as page texts, and their rendering for the model."""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.schema import DocumentType


@dataclass
class Document:
    id: str  # doc_1, doc_2, ...
    filename: str
    pages: list[str]
    type: DocumentType | None = None
    ocr_pages: list[int] = field(default_factory=list)  # 1-based pages read by OCR

    @property
    def page_count(self) -> int:
        return len(self.pages)


def render_document(doc: Document, max_pages: int | None = None) -> str:
    """Text with page tags. Page text is passed unchanged so quotes match it."""
    pages = doc.pages if max_pages is None else doc.pages[:max_pages]
    type_attr = f' type="{doc.type}"' if doc.type else ""
    body = "\n".join(f'<page number="{i}">\n{text}\n</page>' for i, text in enumerate(pages, start=1))
    return f'<document id="{doc.id}"{type_attr}>\n{body}\n</document>'
