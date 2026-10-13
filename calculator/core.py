"""Deterministic delay-penalty calculator (CLAUDE.md, section 6).

No LLM is involved here. Money is kept in integer grosze, intermediate
math in Decimal, and rounding happens once on each final amount.
Every result carries a calculation path (steps) for the UI.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from calculator.money import format_pln, round_grosze
from calculator.rates import RateTable

ONE_DAY = dt.timedelta(days=1)


class Basis(StrEnum):
    PERCENT_OF_PRICE_PER_DAY = "percent_of_price_per_day"
    FIXED_PER_DAY = "fixed_per_day"
    STATUTORY_INTEREST = "statutory_interest"
    OTHER = "other"


class Event(StrEnum):
    HANDOVER_DELAY = "handover_delay"
    TRANSFER_DELAY = "transfer_delay"


EVENT_LABELS = {
    Event.HANDOVER_DELAY: "opóźnienie w wydaniu lokalu",
    Event.TRANSFER_DELAY: "opóźnienie w zawarciu umowy przenoszącej własność",
}


class CalculationError(ValueError):
    pass


@dataclass(frozen=True)
class CalcConfig:
    """Counting conventions. All of them must be confirmed by a lawyer."""

    include_actual_date: bool
    interest_year_days: int = 365
    rounding: str = ROUND_HALF_UP
    verified: bool = False


@dataclass(frozen=True)
class Step:
    label: str
    formula: str
    result: str


@dataclass(frozen=True)
class Amendment:
    """Deadline changed by an annex."""

    new_deadline: dt.date
    annex_no: int | None = None


@dataclass(frozen=True)
class EffectiveDeadline:
    deadline: dt.date
    source: str  # "contract" | "annex"
    annex_no: int | None = None

    def describe(self) -> str:
        if self.source == "contract":
            return "umowa"
        return f"aneks nr {self.annex_no}" if self.annex_no is not None else "aneks (bez numeru)"


@dataclass(frozen=True)
class Cap:
    type: str  # "percent" | "amount"
    value: Decimal  # fraction of price for percent, PLN for amount


@dataclass(frozen=True)
class Terms:
    basis: Basis
    price_grosze: int
    rate: Decimal | None = None  # daily fraction, or PLN/day for fixed_per_day
    cap: Cap | None = None
    interest_table: RateTable | None = None


@dataclass(frozen=True)
class InterestSegment:
    start: dt.date
    end: dt.date  # inclusive
    days: int
    annual_rate: Decimal
    source: str


@dataclass(frozen=True)
class InterestResult:
    grosze: int
    segments: tuple[InterestSegment, ...]
    all_rates_verified: bool


@dataclass
class PenaltyResult:
    event: Event
    effective_deadline: EffectiveDeadline
    end_date: dt.date
    ongoing: bool
    days: int
    uncapped_grosze: int | None
    cap_grosze: int | None
    capped_grosze: int | None
    steps: list[Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def cap_reached(self) -> bool:
        return (
            self.cap_grosze is not None
            and self.uncapped_grosze is not None
            and self.uncapped_grosze > self.cap_grosze
        )


def fmt_date(day: dt.date) -> str:
    return day.strftime("%d.%m.%Y")


def fmt_percent(fraction: Decimal) -> str:
    text = format((fraction * 100).normalize(), "f")
    return text.replace(".", ",") + "%"


def effective_deadline(contract_deadline: dt.date | None, amendments: list[Amendment]) -> EffectiveDeadline:
    """The annex takes precedence over the contract; the latest annex over earlier ones.

    Annexes are ordered by annex number when every annex is numbered,
    otherwise the given (document) order is kept. The last one wins.
    """
    if amendments:
        ordered = list(amendments)
        if all(a.annex_no is not None for a in ordered):
            ordered.sort(key=lambda a: a.annex_no)  # type: ignore[arg-type, return-value]
        last = ordered[-1]
        return EffectiveDeadline(last.new_deadline, "annex", last.annex_no)
    if contract_deadline is None:
        raise CalculationError("brak terminu w umowie i w aneksach")
    return EffectiveDeadline(contract_deadline, "contract")


def delay_period(deadline: dt.date, end: dt.date, config: CalcConfig) -> tuple[dt.date, dt.date, int]:
    """First day, last day (inclusive) and number of days of delay.

    Delay starts the day after the deadline. Whether `end` itself counts
    depends on config.include_actual_date. Zero days when not late.
    """
    first = deadline + ONE_DAY
    last = end if config.include_actual_date else end - ONE_DAY
    days = (last - first).days + 1
    if days <= 0:
        return first, first - ONE_DAY, 0
    return first, last, days


def statutory_interest(
    principal_grosze: int,
    first_day: dt.date,
    last_day: dt.date,
    table: RateTable,
    config: CalcConfig,
) -> InterestResult:
    """Simple interest over [first_day, last_day], split by rate periods."""
    if last_day < first_day:
        return InterestResult(0, (), table.all_verified)
    segments: list[InterestSegment] = []
    exact = Decimal(0)
    day = first_day
    while day <= last_day:
        period = table.rate_for(day)
        seg_end = last_day if period.end is None else min(period.end, last_day)
        days = (seg_end - day).days + 1
        segments.append(InterestSegment(day, seg_end, days, period.rate, period.source))
        exact += Decimal(principal_grosze) * period.rate * days / config.interest_year_days
        day = seg_end + ONE_DAY
    used_verified = all(table.rate_for(s.start).verified for s in segments)
    return InterestResult(round_grosze(exact, config.rounding), tuple(segments), used_verified)


def compute_penalty(
    event: Event,
    contract_deadline: dt.date | None,
    amendments: list[Amendment],
    actual_date: dt.date | None,
    as_of: dt.date,
    terms: Terms,
    config: CalcConfig,
) -> PenaltyResult:
    """Penalty for one event (handover or transfer delay)."""
    eff = effective_deadline(contract_deadline, amendments)
    ongoing = actual_date is None
    end = as_of if ongoing else actual_date
    assert end is not None
    first, last, days = delay_period(eff.deadline, end, config)

    result = PenaltyResult(
        event=event,
        effective_deadline=eff,
        end_date=end,
        ongoing=ongoing,
        days=days,
        uncapped_grosze=None,
        cap_grosze=None,
        capped_grosze=None,
    )
    steps = result.steps
    warnings = result.warnings

    steps.append(Step(
        "Termin efektywny",
        f"termin z dokumentu: {eff.describe()}",
        fmt_date(eff.deadline),
    ))
    end_label = f"stan na dzień {fmt_date(end)} (opóźnienie trwa)" if ongoing else f"data faktyczna {fmt_date(end)}"
    inclusion = "wliczając" if config.include_actual_date else "nie wliczając"
    steps.append(Step(
        "Dni opóźnienia",
        f"od {fmt_date(first)} do {end_label}, {inclusion} dnia końcowego",
        str(days),
    ))
    if ongoing:
        warnings.append(f"Brak daty faktycznej — opóźnienie liczone na dzień {fmt_date(as_of)}.")
    if not config.verified:
        warnings.append("Sposób liczenia dni nie został potwierdzony przez prawnika (config/calculator.yaml).")

    if terms.basis is Basis.OTHER:
        warnings.append("Nietypowy sposób naliczania kary — wymaga ręcznego wyliczenia.")
        return result

    if terms.basis is Basis.PERCENT_OF_PRICE_PER_DAY:
        rate = _require_rate(terms)
        exact = Decimal(terms.price_grosze) * rate * days
        uncapped = round_grosze(exact, config.rounding)
        steps.append(Step(
            "Kara umowna",
            f"{format_pln(terms.price_grosze)} × {fmt_percent(rate)} × {days} dni",
            format_pln(uncapped),
        ))
    elif terms.basis is Basis.FIXED_PER_DAY:
        rate = _require_rate(terms)
        exact = rate * 100 * days
        uncapped = round_grosze(exact, config.rounding)
        steps.append(Step(
            "Kara umowna",
            f"{format_pln(round_grosze(rate * 100))} × {days} dni",
            format_pln(uncapped),
        ))
    else:
        if terms.interest_table is None:
            raise CalculationError("brak tabeli odsetek ustawowych")
        interest = statutory_interest(terms.price_grosze, first, last, terms.interest_table, config)
        uncapped = interest.grosze
        for seg in interest.segments:
            steps.append(Step(
                f"Odsetki {fmt_date(seg.start)}–{fmt_date(seg.end)}",
                f"{format_pln(terms.price_grosze)} × {fmt_percent(seg.annual_rate)} × "
                f"{seg.days}/{config.interest_year_days}",
                seg.source or "brak źródła stawki",
            ))
        steps.append(Step("Suma odsetek", "suma okresów, zaokrąglenie do grosza", format_pln(uncapped)))
        if not interest.all_rates_verified:
            warnings.append("Użyte stawki odsetek nie są oznaczone jako zweryfikowane.")

    result.uncapped_grosze = uncapped
    result.capped_grosze = uncapped

    if terms.cap is not None:
        cap_grosze = _cap_grosze(terms.cap, terms.price_grosze, config)
        result.cap_grosze = cap_grosze
        result.capped_grosze = min(uncapped, cap_grosze)
        cap_formula = (
            f"{format_pln(terms.price_grosze)} × {fmt_percent(terms.cap.value)}"
            if terms.cap.type == "percent"
            else "kwota wskazana w umowie"
        )
        steps.append(Step("Limit kary", cap_formula, format_pln(cap_grosze)))
        steps.append(Step(
            "Kara po zastosowaniu limitu",
            f"min({format_pln(uncapped)}, {format_pln(cap_grosze)})",
            format_pln(result.capped_grosze),
        ))
        warnings.append("Umowa ogranicza wysokość kary — klauzula potencjalnie abuzywna, do oceny prawnika.")

    return result


def _require_rate(terms: Terms) -> Decimal:
    if terms.rate is None:
        raise CalculationError("brak stawki kary")
    return terms.rate


def _cap_grosze(cap: Cap, price_grosze: int, config: CalcConfig) -> int:
    if cap.type == "percent":
        return round_grosze(Decimal(price_grosze) * cap.value, config.rounding)
    if cap.type == "amount":
        return round_grosze(cap.value * 100, config.rounding)
    raise CalculationError(f"nieznany typ limitu: {cap.type}")
