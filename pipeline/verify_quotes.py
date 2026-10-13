"""Quote verification (CLAUDE.md, section 3, rule 2).

Every extracted value must be backed by a verbatim quote found in the
document text. This step owns `needs_review`: it overwrites whatever the
model returned. Issues are reported separately (field path + reason) so
the schema does not need extra fields.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pipeline.schema import Extraction, Field

# Typographic variants that PDF text layers and models swap freely.
_CHAR_MAP = str.maketrans({
    "„": '"', "”": '"', "“": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'",
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    " ": " ", " ": " ", " ": " ",
})
_SOFT_HYPHEN = "­"
_WS = re.compile(r"\s+")
_LINE_BREAK_HYPHEN = re.compile(r"(\w)-\s*\n\s*(\w)")


class Issue(StrEnum):
    QUOTE_MISSING = "quote_missing"  # value present, no quote
    QUOTE_NOT_FOUND = "quote_not_found"
    PAGE_MISMATCH = "page_mismatch"  # found, but on a different page
    PAGE_MISSING = "page_missing"
    UNKNOWN_DOCUMENT = "unknown_document"
    LOW_CONFIDENCE = "low_confidence"
    VALUE_UNRESOLVED = "value_unresolved"  # clause quoted, value not determinable


@dataclass(frozen=True)
class QuoteIssue:
    path: str
    issue: Issue
    found_page: int | None = None


def normalize(text: str, *, join_hyphenation: bool = False) -> str:
    text = unicodedata.normalize("NFKC", text).replace(_SOFT_HYPHEN, "")
    if join_hyphenation:
        text = _LINE_BREAK_HYPHEN.sub(r"\1\2", text)
    text = text.translate(_CHAR_MAP)
    return _WS.sub(" ", text).strip()


class DocumentText:
    """Pages of one document, normalized once for searching."""

    def __init__(self, pages: list[str]) -> None:
        self.pages = pages
        self._variants = [
            [normalize(p, join_hyphenation=j) for p in pages] for j in (False, True)
        ]

    def find(self, quote: str) -> list[int]:
        """1-based pages where the quote starts (also across a page break)."""
        hits: list[int] = []
        for join, pages in zip((False, True), self._variants):
            q = normalize(quote, join_hyphenation=join)
            if not q:
                return []
            for i, page in enumerate(pages):
                window = page if i + 1 == len(pages) else f"{page} {pages[i + 1]}"
                pos = window.find(q)
                if pos != -1 and pos < len(page) and (i + 1) not in hits:
                    hits.append(i + 1)
            if hits:
                return hits
        return hits


def verify_field(path: str, field: Field[Any], docs: dict[str, DocumentText]) -> list[QuoteIssue]:
    """Check one field and set its needs_review flag."""
    issues: list[QuoteIssue] = []
    if field.value is None and field.quote is None:
        field.needs_review = False
        return issues

    if not field.quote:
        issues.append(QuoteIssue(path, Issue.QUOTE_MISSING))
    else:
        doc = docs.get(field.document_id or "")
        if doc is None and len(docs) == 1 and field.document_id is None:
            doc = next(iter(docs.values()))
        if doc is None:
            issues.append(QuoteIssue(path, Issue.UNKNOWN_DOCUMENT))
        else:
            pages = doc.find(field.quote)
            if not pages:
                issues.append(QuoteIssue(path, Issue.QUOTE_NOT_FOUND))
            elif field.page is None:
                issues.append(QuoteIssue(path, Issue.PAGE_MISSING, pages[0]))
            elif field.page not in pages:
                issues.append(QuoteIssue(path, Issue.PAGE_MISMATCH, pages[0]))

    if field.value is None:
        issues.append(QuoteIssue(path, Issue.VALUE_UNRESOLVED))
    if field.confidence == "low":
        issues.append(QuoteIssue(path, Issue.LOW_CONFIDENCE))
    field.needs_review = bool(issues)
    return issues


def verify_extraction(extraction: Extraction, documents: dict[str, list[str]]) -> list[QuoteIssue]:
    """Verify all fields in place. `documents` maps document_id -> page texts."""
    docs = {doc_id: DocumentText(pages) for doc_id, pages in documents.items()}
    issues: list[QuoteIssue] = []
    for path, field in extraction.iter_fields():
        issues.extend(verify_field(path, field, docs))
    return issues
