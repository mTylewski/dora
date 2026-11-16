"""Formatting of extracted values for display and for the edit inputs."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from calculator.core import fmt_percent
from calculator.money import format_pln, round_grosze

BASIS_LABELS = {
    "percent_of_price_per_day": "% ceny za dzień",
    "fixed_per_day": "stała kwota za dzień",
    "statutory_interest": "odsetki ustawowe",
    "other": "inny sposób",
}
EVENT_LABELS = {"handover_delay": "opóźnienie wydania lokalu", "transfer_delay": "opóźnienie umowy przenoszącej"}
ISSUE_LABELS = {
    "quote_missing": "brak cytatu",
    "quote_not_found": "cytatu nie znaleziono w dokumencie",
    "page_mismatch": "cytat jest na innej stronie",
    "page_missing": "brak numeru strony",
    "unknown_document": "nieznany dokument",
    "low_confidence": "niska pewność",
    "value_unresolved": "wartości nie da się ustalić z dokumentu",
}


def _date(value: str) -> str:
    return dt.date.fromisoformat(value).strftime("%d.%m.%Y")


def display_value(path: str, value: Any, basis: str | None = None) -> str:
    if value is None:
        return "—"
    if path.startswith("annex_deadlines"):
        what = "wydanie lokalu" if value["field"] == "handover_deadline" else "umowa przenosząca"
        no = f"aneks nr {value['annex_no']}" if value.get("annex_no") is not None else "aneks"
        return f"{_date(value['date'])} ({what}, {no})"
    if path.startswith("liability_exclusions"):
        return str(value)
    if path == "price_gross":
        return format_pln(round_grosze(Decimal(value) * 100))
    if path == "penalty_rate":
        if basis == "fixed_per_day":
            return format_pln(round_grosze(Decimal(value) * 100)) + " / dzień"
        return fmt_percent(Decimal(value)) + " ceny / dzień"
    if path == "penalty_basis":
        return BASIS_LABELS.get(value, value)
    if path == "penalty_cap":
        if value["type"] == "percent":
            return fmt_percent(Decimal(value["value"])) + " ceny"
        return format_pln(round_grosze(Decimal(value["value"]) * 100))
    if path == "penalty_events":
        return ", ".join(EVENT_LABELS.get(v, v) for v in value) or "—"
    if isinstance(value, bool):
        return "tak" if value else "nie"
    if path.endswith("_date") or path.endswith("_deadline"):
        return _date(value)
    return str(value)


def edit_value(path: str, value: Any) -> str:
    if value is None:
        return ""
    if path.startswith("annex_deadlines"):
        return _date(value["date"])
    if path == "price_gross":
        zl, gr = divmod(round_grosze(Decimal(value) * 100), 100)
        return f"{zl:,}".replace(",", " ") + f",{gr:02d}"
    if path == "penalty_cap":
        if value["type"] == "percent":
            return format(Decimal(value["value"]) * 100, "f").rstrip("0").rstrip(".") + "%"
        return str(value["value"])
    if path == "penalty_events":
        return ", ".join(value)
    if isinstance(value, bool):
        return "tak" if value else "nie"
    if path.endswith("_date") or path.endswith("_deadline"):
        return _date(value)
    return str(value)


BOOL_FIELDS = ("exclusive_penalty_clause", "waiver_of_claims")
NONE_LABEL = "— brak w dokumencie —"


def edit_choices(path: str, value: Any) -> list[tuple[str, str, bool]] | None:
    """Options (value sent to the server, Polish label, selected) for fields with a fixed set of
    values, shown as a drop-down instead of a text box with internal codes. None = text box."""
    if path == "penalty_basis":
        options = [("", NONE_LABEL)] + list(BASIS_LABELS.items())
    elif path == "penalty_events":
        options = [("", NONE_LABEL)] + list(EVENT_LABELS.items()) + [
            ("handover_delay, transfer_delay", "oba: " + " i ".join(EVENT_LABELS.values()))]
        if isinstance(value, list):  # canonical order, as in the options
            value = [e for e in EVENT_LABELS if e in value] + [e for e in value if e not in EVENT_LABELS]
    elif path in BOOL_FIELDS:
        options = [("", NONE_LABEL), ("tak", "tak"), ("nie", "nie")]
    else:
        return None
    current = edit_value(path, value)
    if current not in {code for code, _ in options}:  # unexpected value: keep it selectable, never lose it
        options.append((current, display_value(path, value)))
    return [(code, label, code == current) for code, label in options]


def edit_hint(path: str) -> str:
    if path.startswith("annex_deadlines") or path.endswith("_date") or path.endswith("_deadline"):
        return "DD.MM.RRRR"
    return {
        "price_gross": "kwota w zł, np. 450000,00",
        "penalty_rate": "np. 0,02% dziennie (albo ułamek 0,0002); przy stałej kwocie: zł/dzień",
        "penalty_basis": ", ".join(BASIS_LABELS),
        "penalty_cap": "np. 5% albo 20000; puste = brak",
        "penalty_events": "handover_delay, transfer_delay",
        "exclusive_penalty_clause": "tak / nie / brak",
        "waiver_of_claims": "tak / nie / brak",
    }.get(path, "")
