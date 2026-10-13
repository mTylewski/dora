"""Scoring of pipeline results against hand-labelled expectations (CLAUDE.md, section 10)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

CRITICAL_FIELDS = ("price_gross", "handover_deadline", "transfer_deadline", "penalty_rate", "penalty_cap")
OTHER_FIELDS = ("developer_name", "agreement_reference", "agreement_date", "penalty_basis", "penalty_events", "annex_deadlines", "exclusive_penalty_clause",
                "waiver_of_claims", "actual_handover_date", "actual_transfer_date")

THRESHOLDS = {
    "critical_accuracy": 0.95,
    "other_accuracy": 0.90,
    "quotes_found_or_flagged": 1.0,
    "clause_recall": 0.90,
    "clause_false_alarm_rate": 0.20,  # max
    "max_seconds_per_case": 300,
    "calculator_accuracy": 1.0,
}


def _norm(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in ("price_gross", "penalty_rate"):
        return Decimal(str(value)).normalize()
    if name.endswith("_deadline") or name.endswith("_date"):
        return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
    if name == "penalty_cap":
        return (value["type"], Decimal(str(value["value"])).normalize())
    if name == "penalty_events":
        return frozenset(value)
    if name == "annex_deadlines":
        return frozenset(
            (_norm("x_date", a["date"]), a["field"], a.get("annex_no")) for a in value
        )
    return value


def field_matches(name: str, expected: Any, actual: Any) -> bool:
    return _norm(name, expected) == _norm(name, actual)


def actual_values(extraction: dict[str, Any]) -> dict[str, Any]:
    """Plain values from Extraction.model_dump(mode='json')."""
    out = {name: extraction[name]["value"] for name in CRITICAL_FIELDS + OTHER_FIELDS if name != "annex_deadlines"}
    out["annex_deadlines"] = [a["value"] for a in extraction.get("annex_deadlines", []) if a["value"]]
    return out


@dataclass
class CaseScore:
    name: str
    field_hits: dict[str, bool] = field(default_factory=dict)
    quotes_total: int = 0
    quotes_found: int = 0
    quotes_flagged: int = 0
    clause_tp: int = 0
    clause_fn: int = 0
    clause_fp: int = 0
    seconds: float = 0.0
    calculator_ok: bool | None = None

    @property
    def quotes_unaccounted(self) -> int:
        return self.quotes_total - self.quotes_found - self.quotes_flagged


def score_case(name: str, expected: dict[str, Any], extraction: dict[str, Any], issues: list[dict[str, Any]],
               clause_ids: list[str], seconds: float,
               penalties_grosze: list[int] | None = None) -> CaseScore:
    s = CaseScore(name=name, seconds=seconds)
    actual = actual_values(extraction)
    for f in CRITICAL_FIELDS + OTHER_FIELDS:
        if f in expected["fields"]:
            s.field_hits[f] = field_matches(f, expected["fields"][f], actual.get(f))

    flagged_paths = {i["path"] for i in issues}
    for name_, item in _iter_fields(extraction):
        if item.get("quote") or item.get("value") is not None:
            s.quotes_total += 1
            if name_ in flagged_paths or item.get("needs_review"):
                s.quotes_flagged += 1
            else:
                s.quotes_found += 1

    want = set(expected.get("clauses", []))
    got = set(clause_ids)
    s.clause_tp, s.clause_fn, s.clause_fp = len(want & got), len(want - got), len(got - want)

    if "penalties_grosze" in expected and penalties_grosze is not None:
        s.calculator_ok = sorted(expected["penalties_grosze"]) == sorted(penalties_grosze)
    return s


def _iter_fields(extraction: dict[str, Any]):
    for name, item in extraction.items():
        if isinstance(item, dict) and "value" in item:
            yield name, item
        elif isinstance(item, list):
            for i, sub in enumerate(item):
                yield f"{name}[{i}]", sub


def summarize(scores: list[CaseScore]) -> dict[str, Any]:
    def accuracy(fields: tuple[str, ...]) -> float | None:
        hits = [h for s in scores for f, h in s.field_hits.items() if f in fields]
        return sum(hits) / len(hits) if hits else None

    per_field = {}
    for f in CRITICAL_FIELDS + OTHER_FIELDS:
        hits = [s.field_hits[f] for s in scores if f in s.field_hits]
        if hits:
            per_field[f] = sum(hits) / len(hits)

    quotes_total = sum(s.quotes_total for s in scores)
    accounted = sum(s.quotes_found + s.quotes_flagged for s in scores)
    tp = sum(s.clause_tp for s in scores)
    fn = sum(s.clause_fn for s in scores)
    fp = sum(s.clause_fp for s in scores)
    calc = [s.calculator_ok for s in scores if s.calculator_ok is not None]
    return {
        "cases": len(scores),
        "critical_accuracy": accuracy(CRITICAL_FIELDS),
        "other_accuracy": accuracy(OTHER_FIELDS),
        "per_field": per_field,
        "quotes_found_rate": (sum(s.quotes_found for s in scores) / quotes_total) if quotes_total else None,
        "quotes_found_or_flagged": (accounted / quotes_total) if quotes_total else None,
        "clause_recall": tp / (tp + fn) if (tp + fn) else None,
        "clause_false_alarm_rate": fp / (tp + fp) if (tp + fp) else None,
        "max_seconds_per_case": max((s.seconds for s in scores), default=None),
        "calculator_accuracy": (sum(calc) / len(calc)) if calc else None,
        "failed_fields": sorted(f"{s.name}:{f}" for s in scores for f, h in s.field_hits.items() if not h),
    }


def check_thresholds(summary: dict[str, Any]) -> list[str]:
    failures = []
    for key, limit in THRESHOLDS.items():
        value = summary.get(key)
        if value is None:
            continue
        upper_bound = key in ("clause_false_alarm_rate", "max_seconds_per_case")
        if (value > limit) if upper_bound else (value < limit):
            failures.append(f"{key}={value:.3f} (próg {'≤' if upper_bound else '≥'} {limit})")
    return failures


def regressions(current: dict[str, Any], previous: dict[str, Any] | None, tolerance: float = 0.0) -> list[str]:
    """Per-field accuracy drops compared with the previous report."""
    if not previous:
        return []
    out = []
    for f, prev in previous.get("per_field", {}).items():
        cur = current.get("per_field", {}).get(f)
        if cur is not None and cur < prev - tolerance:
            out.append(f"{f}: {prev:.3f} → {cur:.3f}")
    return out
