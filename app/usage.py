"""Usage report and CSV exports for evaluation (admin only).

Everything here is technical metadata: ids, steps, models, durations, token counts,
outcome codes and field names. No document content and no personal data.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AccessLog, Case, CaseRun, LlmCall

REVIEW_ACTIONS = ("confirm", "correct", "revert")

LLM_CALL_COLUMNS = ["at", "case_id", "step", "attempt", "model", "served_model", "duration_ms", "outcome",
                    "stop_reason", "input_tokens", "output_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens", "cost_microusd"]
CASE_RUN_COLUMNS = ["at", "case_id", "stage", "outcome", "error_code", "duration_ms", "documents", "pages",
                    "ocr_pages", "empty_pages", "replacements", "fields_total", "fields_empty",
                    "fields_needs_review", "quote_issues", "clause_flags"]
FIELD_REVIEW_COLUMNS = ["at", "case_id", "action", "field"]


@dataclass
class Bucket:
    calls: int = 0
    ok: int = 0
    failed: int = 0
    retries: int = 0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0
    cost_microusd: int = 0
    unpriced: int = 0  # calls without a price in config/pricing.yaml

    def add(self, c: LlmCall) -> None:
        self.calls += 1
        self.ok += c.outcome == "ok"
        self.failed += c.outcome != "ok"
        self.retries += c.attempt > 1
        self.duration_ms += c.duration_ms
        self.input_tokens += c.input_tokens
        self.output_tokens += c.output_tokens
        self.cache_write += c.cache_creation_input_tokens
        self.cache_read += c.cache_read_input_tokens
        if c.cost_microusd is None:
            self.unpriced += 1
        else:
            self.cost_microusd += c.cost_microusd

    @property
    def avg_s(self) -> float:
        return self.duration_ms / self.calls / 1000 if self.calls else 0.0


@dataclass
class CaseRow:
    case_id: str
    case_number: str | None
    exists: bool
    analyses: int = 0
    failed_analyses: int = 0
    pages: int | None = None
    ocr_pages: int | None = None
    prepare_s: float | None = None
    analyze_s: float | None = None
    fields_needs_review: int | None = None
    fields_empty: int | None = None
    clause_flags: int | None = None
    last_error: str | None = None
    reviews: int = 0
    corrections: int = 0
    llm: Bucket = field(default_factory=Bucket)
    last_at: dt.datetime | None = None


@dataclass
class FieldReview:
    field: str
    confirmed: int = 0
    corrected: int = 0
    reverted: int = 0

    @property
    def corrected_share(self) -> float | None:
        decided = self.confirmed + self.corrected
        return self.corrected / decided if decided else None


@dataclass
class UsageReport:
    since: dt.datetime | None
    total: Bucket
    by_step: list[tuple[str, str, Bucket]]
    cases: list[CaseRow]
    fields: list[FieldReview]

    @property
    def analyzed(self) -> list[CaseRow]:
        """Cases with at least one successful analysis."""
        return [c for c in self.cases if c.analyses > c.failed_analyses]

    @property
    def avg_analyze_s(self) -> float | None:
        times = [c.analyze_s for c in self.analyzed if c.analyze_s is not None]
        return sum(times) / len(times) if times else None

    @property
    def avg_cost_microusd(self) -> int | None:
        priced = [c.llm.cost_microusd for c in self.analyzed if c.llm.calls and not c.llm.unpriced]
        return round(sum(priced) / len(priced)) if priced else None

    @property
    def avg_needs_review(self) -> float | None:
        counts = [c.fields_needs_review for c in self.analyzed if c.fields_needs_review is not None]
        return sum(counts) / len(counts) if counts else None

    @property
    def corrected_share(self) -> float | None:
        confirmed = sum(f.confirmed for f in self.fields)
        corrected = sum(f.corrected for f in self.fields)
        return corrected / (confirmed + corrected) if confirmed + corrected else None

    @property
    def failed_analyses(self) -> int:
        return sum(c.failed_analyses for c in self.cases)


def _review(action: str) -> tuple[str, str] | None:
    kind, _, path = action.partition(":")
    return (kind, path) if kind in REVIEW_ACTIONS and path else None


def build_report(db: Session, since: dt.datetime | None = None) -> UsageReport:
    def recent(model, column):
        q = select(model).order_by(column)
        return q.where(column >= since) if since else q

    calls = list(db.scalars(recent(LlmCall, LlmCall.at)))
    runs = list(db.scalars(recent(CaseRun, CaseRun.at)))
    logs = [e for e in db.scalars(recent(AccessLog, AccessLog.at)) if _review(e.action)]

    total = Bucket()
    steps: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    case_ids: list[str] = []
    rows: dict[str, CaseRow] = {}
    numbers = {c.id: c.case_number for c in db.scalars(select(Case))}

    def row(case_id: str) -> CaseRow:
        if case_id not in rows:
            rows[case_id] = CaseRow(case_id, numbers.get(case_id), case_id in numbers)
            case_ids.append(case_id)
        return rows[case_id]

    for r in runs:
        cr = row(r.case_id)
        cr.last_at = r.at
        if r.stage == "prepare":
            cr.pages, cr.ocr_pages, cr.prepare_s = r.pages, r.ocr_pages, r.duration_ms / 1000
        elif r.stage == "analyze":
            cr.analyses += 1
            cr.analyze_s = r.duration_ms / 1000
            if r.outcome == "ok":
                cr.fields_needs_review, cr.fields_empty, cr.clause_flags = (
                    r.fields_needs_review, r.fields_empty, r.clause_flags)
            else:
                cr.failed_analyses += 1
        if r.error_code:
            cr.last_error = r.error_code
    for c in calls:
        total.add(c)
        steps[(c.step, c.model)].add(c)
        cr = row(c.case_id)
        cr.llm.add(c)
        cr.last_at = max(cr.last_at or c.at, c.at)

    reviews: dict[str, FieldReview] = {}
    for e in logs:
        kind, path = _review(e.action)
        fr = reviews.setdefault(path, FieldReview(path))
        cr = row(e.case_id) if e.case_id else None
        if kind == "confirm":
            fr.confirmed += 1
        elif kind == "correct":
            fr.corrected += 1
            if cr:
                cr.corrections += 1
        else:
            fr.reverted += 1
        if cr:
            cr.reviews += 1

    order = ["classify", "extract", "clauses", "letter"]
    by_step = sorted(((s, m, b) for (s, m), b in steps.items()),
                     key=lambda t: (order.index(t[0]) if t[0] in order else len(order), t[0], t[1]))
    cases = sorted(rows.values(), key=lambda r: r.last_at or dt.datetime.min, reverse=True)
    fields = sorted(reviews.values(), key=lambda f: (-(f.corrected_share or 0), f.field))
    return UsageReport(since, total, by_step, cases, fields)


def _csv(columns: list[str], records: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for rec in records:
        writer.writerow({k: (v.isoformat(sep=" ", timespec="seconds") if isinstance(v, dt.datetime) else v)
                         for k, v in rec.items()})
    return buf.getvalue()


def export_csv(db: Session, name: str) -> str:
    """CSV text for one export: llm_calls, case_runs or field_reviews."""
    if name == "llm_calls":
        rows = db.scalars(select(LlmCall).order_by(LlmCall.at))
        return _csv(LLM_CALL_COLUMNS, [{c: getattr(r, c) for c in LLM_CALL_COLUMNS} for r in rows])
    if name == "case_runs":
        rows = db.scalars(select(CaseRun).order_by(CaseRun.at))
        return _csv(CASE_RUN_COLUMNS, [{c: getattr(r, c) for c in CASE_RUN_COLUMNS} for r in rows])
    if name == "field_reviews":
        records = []
        for e in db.scalars(select(AccessLog).order_by(AccessLog.at)):
            review = _review(e.action)
            if review:
                records.append({"at": e.at, "case_id": e.case_id, "action": review[0], "field": review[1]})
        return _csv(FIELD_REVIEW_COLUMNS, records)
    raise KeyError(name)


EXPORTS = ("llm_calls", "case_runs", "field_reviews")
