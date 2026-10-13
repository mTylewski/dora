"""Case-level calculation: both delay events plus a timeline."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from calculator.core import (
    EVENT_LABELS,
    Amendment,
    CalcConfig,
    CalculationError,
    Event,
    PenaltyResult,
    Terms,
    compute_penalty,
)


@dataclass(frozen=True)
class CaseInput:
    terms: Terms
    penalty_events: tuple[Event, ...]
    as_of: dt.date
    handover_deadline: dt.date | None = None
    transfer_deadline: dt.date | None = None
    handover_amendments: tuple[Amendment, ...] = ()
    transfer_amendments: tuple[Amendment, ...] = ()
    actual_handover_date: dt.date | None = None
    actual_transfer_date: dt.date | None = None


@dataclass(frozen=True)
class TimelineEntry:
    date: dt.date
    label: str
    kind: str  # "deadline" | "annex" | "actual" | "as_of"


@dataclass
class CaseResult:
    penalties: list[PenaltyResult]
    skipped: list[str] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)

    @property
    def total_uncapped_grosze(self) -> int:
        return sum(p.uncapped_grosze or 0 for p in self.penalties)

    @property
    def total_capped_grosze(self) -> int:
        return sum(p.capped_grosze or 0 for p in self.penalties)


def calculate_case(case: CaseInput, config: CalcConfig) -> CaseResult:
    result = CaseResult(penalties=[])
    plan = (
        (Event.HANDOVER_DELAY, case.handover_deadline, case.handover_amendments, case.actual_handover_date),
        (Event.TRANSFER_DELAY, case.transfer_deadline, case.transfer_amendments, case.actual_transfer_date),
    )
    for event, deadline, amendments, actual in plan:
        if event not in case.penalty_events:
            continue
        try:
            penalty = compute_penalty(event, deadline, list(amendments), actual, case.as_of, case.terms, config)
        except CalculationError as exc:
            result.skipped.append(f"{EVENT_LABELS[event]}: {exc}")
            continue
        result.penalties.append(penalty)
    result.timeline = build_timeline(case)
    return result


def build_timeline(case: CaseInput) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    if case.handover_deadline:
        entries.append(TimelineEntry(case.handover_deadline, "Termin wydania lokalu (umowa)", "deadline"))
    if case.transfer_deadline:
        entries.append(TimelineEntry(case.transfer_deadline, "Termin umowy przenoszącej (umowa)", "deadline"))
    for what, amendments in (("wydania lokalu", case.handover_amendments), ("umowy przenoszącej", case.transfer_amendments)):
        for a in amendments:
            no = f"nr {a.annex_no}" if a.annex_no is not None else "bez numeru"
            entries.append(TimelineEntry(a.new_deadline, f"Termin {what} (aneks {no})", "annex"))
    if case.actual_handover_date:
        entries.append(TimelineEntry(case.actual_handover_date, "Faktyczne wydanie lokalu", "actual"))
    if case.actual_transfer_date:
        entries.append(TimelineEntry(case.actual_transfer_date, "Zawarcie umowy przenoszącej", "actual"))
    entries.append(TimelineEntry(case.as_of, "Data wyliczenia", "as_of"))
    return sorted(entries, key=lambda e: e.date)


def load_calc_config(path: Path) -> CalcConfig:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    day_count = data["day_count"]
    include = day_count.get("include_actual_date")
    if not isinstance(include, bool):
        raise CalculationError("config: day_count.include_actual_date must be true or false")
    return CalcConfig(
        include_actual_date=include,
        interest_year_days=int(data.get("interest_year_days", 365)),
        rounding=str(data.get("rounding", "ROUND_HALF_UP")),
        verified=bool(day_count.get("verified", False)),
    )
