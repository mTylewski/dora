"""Step 6: flag clauses matching the pattern library (clauses/*.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from pipeline.documents import Document, render_document
from pipeline.llm import LLMClient, call_structured
from pipeline.schema import Confidence, strict_schema
from pipeline.settings import CLAUSES_DIR, StepSettings, load_step, read_prompt
from pipeline.verify_quotes import DocumentText, Issue, QuoteIssue


@dataclass(frozen=True)
class ClausePattern:
    id: str
    title: str
    pattern_description: str
    why_risky: str
    source: str
    verified: bool


class ClauseFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str
    quote: str
    page: int | None
    document_id: str | None
    reasoning: str
    confidence: Confidence
    needs_review: bool = False  # set by code


class ClauseFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flags: list[ClauseFlag]


def clauses_output_json_schema() -> dict:
    return strict_schema(ClauseFlags.model_json_schema(), ("needs_review",))


def load_library(directory: Path | None = None) -> list[ClausePattern]:
    directory = directory or CLAUSES_DIR
    patterns: list[ClausePattern] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            for raw in yaml.safe_load(fh) or []:
                patterns.append(ClausePattern(
                    id=raw["id"], title=raw["title"], pattern_description=raw["pattern_description"],
                    why_risky=raw["why_risky"], source=str(raw.get("source") or ""),
                    verified=bool(raw.get("verified", False)),
                ))
    ids = [p.id for p in patterns]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate clause ids: {sorted(duplicates)}")
    return patterns


def render_library(patterns: list[ClausePattern]) -> str:
    """Stable text (sorted by id) so the cached system prompt prefix never changes between cases."""
    blocks = [
        f"- id: {p.id}\n  title: {p.title}\n  pattern: {p.pattern_description}\n  why it matters: {p.why_risky}"
        for p in sorted(patterns, key=lambda p: p.id)
    ]
    return "\n".join(blocks)


def system_prompt(patterns: list[ClausePattern]) -> str:
    return read_prompt("clauses_system.md").replace("{library}", render_library(patterns))


@dataclass
class ClausesResult:
    flags: list[ClauseFlag]
    issues: list[QuoteIssue]
    dropped_unknown_ids: int


def assess_clauses(
    client: LLMClient,
    case_id: str,
    docs: list[Document],
    patterns: list[ClausePattern] | None = None,
    settings: StepSettings | None = None,
) -> ClausesResult:
    patterns = patterns if patterns is not None else load_library()
    settings = settings or load_step("clauses")
    system = [{"type": "text", "text": system_prompt(patterns), "cache_control": {"type": "ephemeral"}}]
    content = [{"type": "text", "text": render_document(d)} for d in docs]
    content.append({"type": "text", "text": "Flag the clauses that match the pattern library."})
    result = call_structured(
        client, "clauses", case_id, settings, system, content, clauses_output_json_schema(), ClauseFlags,
    )

    known = {p.id for p in patterns}
    texts = {d.id: DocumentText(d.pages) for d in docs}
    flags: list[ClauseFlag] = []
    issues: list[QuoteIssue] = []
    dropped = 0
    for flag in result.flags:
        if flag.clause_id not in known:
            dropped += 1
            continue
        path = f"flags[{len(flags)}]"
        doc = texts.get(flag.document_id or "")
        if doc is None and len(texts) == 1 and flag.document_id is None:
            doc = next(iter(texts.values()))
        flag_issues: list[QuoteIssue] = []
        if doc is None:
            flag_issues.append(QuoteIssue(path, Issue.UNKNOWN_DOCUMENT))
        else:
            pages = doc.find(flag.quote)
            if not pages:
                flag_issues.append(QuoteIssue(path, Issue.QUOTE_NOT_FOUND))
            elif flag.page not in pages:
                flag_issues.append(QuoteIssue(path, Issue.PAGE_MISMATCH, pages[0]))
        flag.needs_review = bool(flag_issues)
        issues.extend(flag_issues)
        flags.append(flag)
    return ClausesResult(flags, issues, dropped)
