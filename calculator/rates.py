"""Statutory interest rate tables loaded from config/statutory_interest.yaml."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


class RateTableError(ValueError):
    pass


@dataclass(frozen=True)
class RatePeriod:
    start: dt.date
    end: dt.date | None  # inclusive; None = still in force
    rate: Decimal  # annual, fraction
    source: str
    verified: bool

    def covers(self, day: dt.date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass(frozen=True)
class RateTable:
    kind: str
    periods: tuple[RatePeriod, ...]

    def __post_init__(self) -> None:
        ordered = sorted(self.periods, key=lambda p: p.start)
        for prev, nxt in zip(ordered, ordered[1:]):
            if prev.end is None or prev.end >= nxt.start:
                raise RateTableError(f"{self.kind}: overlapping periods starting {prev.start} and {nxt.start}")
        object.__setattr__(self, "periods", tuple(ordered))

    def rate_for(self, day: dt.date) -> RatePeriod:
        for period in self.periods:
            if period.covers(day):
                return period
        raise RateTableError(f"{self.kind}: no rate configured for {day.isoformat()}")

    @property
    def all_verified(self) -> bool:
        return all(p.verified for p in self.periods)


def _parse_period(raw: dict[str, Any]) -> RatePeriod:
    try:
        rate = raw["rate"]
        if isinstance(rate, float):
            raise RateTableError("rate must be a quoted string, not a float")
        return RatePeriod(
            start=_as_date(raw["from"]),
            end=_as_date(raw["to"]) if raw.get("to") is not None else None,
            rate=Decimal(str(rate)),
            source=str(raw.get("source") or ""),
            verified=bool(raw.get("verified", False)),
        )
    except KeyError as exc:
        raise RateTableError(f"missing key in rate period: {exc}") from exc


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def parse_rate_table(data: dict[str, Any], kind: str) -> RateTable:
    try:
        raw_periods = data["kinds"][kind]["periods"] or []
    except (KeyError, TypeError) as exc:
        raise RateTableError(f"rate table kind not found: {kind}") from exc
    return RateTable(kind=kind, periods=tuple(_parse_period(p) for p in raw_periods))


def load_rate_table(path: Path, kind: str) -> RateTable:
    with path.open(encoding="utf-8") as fh:
        return parse_rate_table(yaml.safe_load(fh), kind)
