"""Lawyer corrections of extracted values. A corrected field is no longer `needs_review`."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pipeline.schema import Extraction

EDITABLE = {
    "developer_name": "text",
    "agreement_reference": "text",
    "agreement_date": "date",
    "price_gross": "decimal",
    "handover_deadline": "date",
    "transfer_deadline": "date",
    "penalty_basis": "basis",
    "penalty_rate": "decimal",
    "penalty_cap": "cap",
    "penalty_events": "events",
    "exclusive_penalty_clause": "bool",
    "waiver_of_claims": "bool",
    "actual_handover_date": "date",
    "actual_transfer_date": "date",
}
_ANNEX = re.compile(r"annex_deadlines\[(\d+)\]")


class CorrectionError(ValueError):
    pass


def normalize_number(raw: str) -> str:
    """Polish and plain number formats to a Decimal-compatible string.

    "1.080.000,00" / "1 080 000,00" / "1080000,00" / "1080000.00" -> "1080000.00"; "0,01" -> "0.01".
    """
    s = raw.replace("\u00a0", "").replace(" ", "").replace("zł", "").replace("PLN", "").replace("%", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")  # dots are thousands separators, comma is decimal
    elif s.count(".") > 1:
        s = s.replace(".", "")  # 1.080.000
    return s


def parse_decimal(raw: str) -> Decimal:
    try:
        return Decimal(normalize_number(raw))
    except InvalidOperation as exc:
        raise CorrectionError(f"nieprawidłowa liczba: {raw}") from exc


_NUMBER_IN_TEXT = re.compile(r"\d{1,3}(?:[ .\u00a0]\d{3})+(?:,\d+)?|\d+(?:,\d+)?")


def numbers_in_quote(quote: str) -> list[Decimal]:
    out = []
    for m in _NUMBER_IN_TEXT.findall(quote or ""):
        try:
            out.append(Decimal(normalize_number(m)))
        except InvalidOperation:
            continue
    return out


def amount_in_quote(quote: str | None) -> Decimal | None:
    """The single amount (>= 1000) written in a quote, or None when there is none or several."""
    amounts = {n for n in numbers_in_quote(quote or "") if n >= 1000}
    return amounts.pop() if len(amounts) == 1 else None


def value_matches_quote(path: str, value: Any, quote: str | None) -> bool | None:
    """Does a numeric value appear in its quote? None when it cannot be checked."""
    if value is None or not quote:
        return None
    numbers = numbers_in_quote(quote)
    if not numbers:
        return None
    if path == "price_gross":
        return Decimal(str(value)) in numbers
    if path == "penalty_rate":
        v = Decimal(str(value))
        return v in numbers or v * 100 in numbers  # "0,01 %" -> 0.0001
    if path == "penalty_cap" and isinstance(value, dict):
        v = Decimal(str(value["value"]))
        return v in numbers or (value["type"] == "percent" and v * 100 in numbers)
    return None


def parse_date(raw: str) -> str:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise CorrectionError(f"nieprawidłowa data: {raw} (użyj DD.MM.RRRR)")


def parse_value(kind: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "" or raw.lower() in ("brak", "null"):
        return None
    if kind == "decimal":
        return str(parse_decimal(raw))
    if kind == "date":
        return parse_date(raw)
    if kind in ("basis", "text"):
        return raw
    if kind == "bool":
        lowered = raw.lower()
        if lowered in ("tak", "true", "1"):
            return True
        if lowered in ("nie", "false", "0"):
            return False
        raise CorrectionError("wpisz: tak / nie / brak")
    if kind == "cap":
        if raw.endswith("%"):
            return {"type": "percent", "value": str(parse_decimal(raw[:-1]) / 100)}
        return {"type": "amount", "value": str(parse_decimal(raw))}
    if kind == "events":
        return [e.strip() for e in raw.split(",") if e.strip()]
    raise CorrectionError(f"unknown kind {kind}")  # pragma: no cover


def apply_corrections(extraction_json: dict[str, Any], corrections: dict[str, Any]) -> Extraction:
    """Return a validated Extraction with corrections applied. Raises CorrectionError."""
    data = {k: (list(v) if isinstance(v, list) else dict(v)) for k, v in extraction_json.items()}
    # Cases analysed before a schema extension: new fields start empty (to be filled by the lawyer).
    for name, info in Extraction.model_fields.items():
        if name not in data:
            is_list = getattr(info.annotation, "__origin__", None) is list or str(info.annotation).startswith("list")
            data[name] = [] if is_list else {"value": None, "quote": None, "page": None, "document_id": None,
                                             "confidence": "low"}
    for path, correction in corrections.items():
        if path in EDITABLE:
            target = dict(data[path])
            data[path] = target
        elif m := _ANNEX.fullmatch(path):
            items = [dict(i) for i in data["annex_deadlines"]]
            index = int(m.group(1))
            if index >= len(items):
                raise CorrectionError(f"brak pozycji {path}")
            target = items[index]
            data["annex_deadlines"] = items
        else:
            raise CorrectionError(f"pole nie podlega edycji: {path}")
        if path.startswith("annex_deadlines"):
            target["value"] = {**(target.get("value") or {}), "date": correction["value"]}
        else:
            target["value"] = correction["value"]
        target["needs_review"] = False
        target["confidence"] = "high"
    try:
        return Extraction.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        raise CorrectionError(str(exc).splitlines()[0]) from exc


def correction_kind(path: str) -> str:
    if path in EDITABLE:
        return EDITABLE[path]
    if _ANNEX.fullmatch(path):
        return "date"
    raise CorrectionError(f"pole nie podlega edycji: {path}")
