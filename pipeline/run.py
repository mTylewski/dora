"""Fixed pipeline (CLAUDE.md, section 4): no agent, a constant sequence of steps.

Two phases so the lawyer can approve anonymization before anything leaves the server:
  prepare_case()  -> steps 0-1 (local only)
  analyze_case()  -> steps 2-6 (API calls on anonymized text) + calculator
The letter (step 7) is generated on demand by pipeline.letter.build_letter.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pipeline.anonymize import Anonymizer, EntityDetector, anonymize_pages, restore
from pipeline.calculate import CalculationOutcome, calculate_from_extraction
from pipeline.classify import DocumentClass, classify_documents
from pipeline.clauses import ClausesResult, assess_clauses, load_library
from pipeline.documents import Document
from pipeline.extract import ExtractionResult, extract_case
from pipeline.llm import LLMClient
from pipeline.pdf_text import OcrFn, read_pdfs

log = logging.getLogger("claims.pipeline")

Progress = Callable[[str, int], None]  # (description, percent)


@dataclass
class PreparedCase:
    case_id: str
    originals: list[Document]
    anonymized: list[Document]
    mapping: dict[str, str]
    replacements: list[dict[str, str]]  # for the approval screen
    persons: list[dict[str, str | None]] = field(default_factory=list)  # name, role, address (local only)


@dataclass
class CaseAnalysis:
    case_id: str
    classification: list[DocumentClass]
    extraction: ExtractionResult
    clauses: ClausesResult
    calculation: CalculationOutcome
    timings_ms: dict[str, int] = field(default_factory=dict)


def prepare_case(
    case_id: str,
    pdf_paths: list[Path],
    ocr: OcrFn | None = None,
    detectors: list[EntityDetector] | None = None,
    anonymize: bool = True,
    progress: Progress | None = None,
) -> PreparedCase:
    started = time.monotonic()
    def on_page(doc_no: int, docs: int, page: int, pages: int, ocr_used: bool) -> None:
        if progress:
            done = (doc_no - 1 + page / pages) / docs
            what = "OCR" if ocr_used else "odczyt"
            progress(f"Dokument {doc_no} z {docs} — {what}: strona {page} z {pages}", int(5 + done * 85))

    originals = read_pdfs(pdf_paths, ocr, on_page)
    if progress:
        progress("Anonimizacja danych osobowych", 92)
    if anonymize:
        pages, anon = anonymize_pages({d.id: d.pages for d in originals}, detectors)
    else:  # demo / tests only
        pages, anon = {d.id: d.pages for d in originals}, Anonymizer()
    anonymized = [
        Document(d.id, d.filename, pages[d.id], d.type, list(d.ocr_pages)) for d in originals
    ]
    seen: set[tuple[str, str]] = set()
    replacements = []
    for r in anon.replacements:
        if (r.token, r.original) not in seen:
            seen.add((r.token, r.original))
            replacements.append({"token": r.token, "original": r.original, "label": r.label})
    log.info("case=%s step=prepare docs=%d pages=%d ocr_pages=%d ms=%d", case_id, len(originals),
             sum(d.page_count for d in originals), sum(len(d.ocr_pages) for d in originals),
             int((time.monotonic() - started) * 1000))
    persons = [{"token": t, **p} for t, p in anon.persons.items()]
    return PreparedCase(case_id, originals, anonymized, dict(anon.mapping), replacements, persons)


def analyze_case(client: LLMClient, prepared: PreparedCase, as_of: dt.date,
                 progress: Progress | None = None) -> CaseAnalysis:
    docs = prepared.anonymized
    timings: dict[str, int] = {}

    def timed(name, fn):
        started = time.monotonic()
        result = fn()
        timings[name] = int((time.monotonic() - started) * 1000)
        return result

    def step(text: str, pct: int) -> None:
        if progress:
            progress(text, pct)

    step("Rozpoznawanie rodzaju dokumentów", 5)
    classification = timed("classify", lambda: classify_documents(client, prepared.case_id, docs))
    for original, anon in zip(prepared.originals, docs):
        original.type = anon.type
    step("Ekstrakcja danych z cytatami (zwykle 20–60 s)", 15)
    extraction = timed("extract", lambda: extract_case(client, prepared.case_id, docs))
    step("Ocena klauzul (zwykle 20–60 s)", 55)
    clauses = timed("clauses", lambda: assess_clauses(client, prepared.case_id, docs, load_library()))
    step("Wyliczenie kary", 95)
    calculation = timed("calculate", lambda: calculate_from_extraction(extraction.extraction, as_of))
    log.info("case=%s step=analyze timings=%s", prepared.case_id, timings)
    return CaseAnalysis(prepared.case_id, classification, extraction, clauses, calculation, timings)


# --- serialization for the UI / storage ---------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.date,)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def analysis_to_dict(analysis: CaseAnalysis, mapping: dict[str, str] | None = None) -> dict[str, Any]:
    """JSON-ready dict. With `mapping`, quotes are restored to original text (local display only)."""
    def show(text: str | None) -> str | None:
        return restore(text, mapping) if (text and mapping) else text

    ex = analysis.extraction.extraction
    fields = []
    for path, f in ex.iter_fields():
        fields.append({
            "path": path,
            "value": _plain(f.value.model_dump() if hasattr(f.value, "model_dump") else f.value),
            "quote": show(f.quote),
            "page": f.page,
            "document_id": f.document_id,
            "confidence": _plain(f.confidence),
            "needs_review": f.needs_review,
        })
    calc = analysis.calculation
    calc_dict: dict[str, Any] = {"blocking": calc.blocking, "warnings": calc.warnings, "result": None}
    if calc.result is not None:
        calc_dict["result"] = {
            "penalties": [
                {**_plain(asdict(p)), "cap_reached": p.cap_reached} for p in calc.result.penalties
            ],
            "skipped": calc.result.skipped,
            "timeline": _plain([asdict(t) for t in calc.result.timeline]),
            "total_uncapped_grosze": calc.result.total_uncapped_grosze,
            "total_capped_grosze": calc.result.total_capped_grosze,
        }
    return {
        "case_id": analysis.case_id,
        "documents": [_plain(c.model_dump()) for c in analysis.classification],
        "fields": fields,
        "issues": [_plain(asdict(i)) for i in analysis.extraction.issues],
        "clauses": [
            {**_plain(f.model_dump()), "quote": show(f.quote), "reasoning": show(f.reasoning)}
            for f in analysis.clauses.flags
        ],
        "clause_issues": [_plain(asdict(i)) for i in analysis.clauses.issues],
        "calculation": calc_dict,
        "timings_ms": analysis.timings_ms,
    }
