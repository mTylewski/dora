"""Extraction schema (CLAUDE.md, section 5).

Pydantic models are the single source of truth. `schemas/extraction.json`
is generated from them by `scripts/export_schemas.py` and a test checks
that the committed file is up to date.
"""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field as PydanticField

T = TypeVar("T")


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PenaltyBasis(StrEnum):
    PERCENT_OF_PRICE_PER_DAY = "percent_of_price_per_day"
    FIXED_PER_DAY = "fixed_per_day"
    STATUTORY_INTEREST = "statutory_interest"
    OTHER = "other"


class PenaltyEvent(StrEnum):
    HANDOVER_DELAY = "handover_delay"
    TRANSFER_DELAY = "transfer_delay"


class DocumentType(StrEnum):
    DEVELOPMENT_AGREEMENT = "development_agreement"
    ANNEX = "annex"
    HANDOVER_PROTOCOL = "handover_protocol"
    TRANSFER_DEED = "transfer_deed"
    OTHER = "other"


class Field(BaseModel, Generic[T]):
    """One extracted value with its literal source quote."""

    model_config = ConfigDict(extra="forbid")

    value: T | None = PydanticField(
        description="Extracted value; null when the document does not state it. Never guess."
    )
    quote: str | None = PydanticField(
        description="Verbatim fragment of the document supporting the value; null when value is null."
    )
    page: int | None = PydanticField(
        default=None, ge=1, description="1-based page number in the source document."
    )
    document_id: str | None = PydanticField(
        default=None, description="Id of the source document, e.g. doc_1."
    )
    confidence: Confidence = Confidence.LOW
    needs_review: bool = PydanticField(
        default=False, description="Set by code after quote verification, never by the model."
    )


class AnnexDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    field: Literal["handover_deadline", "transfer_deadline"]
    annex_no: int | None = PydanticField(
        default=None, description="Annex number as written in the document; null if not numbered."
    )


class PenaltyCap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["percent", "amount"]
    value: Decimal = PydanticField(
        description="For percent: fraction of price (0.05 = 5%). For amount: PLN."
    )


class Extraction(BaseModel):
    """Case card extracted from all documents of one case."""

    model_config = ConfigDict(extra="forbid")

    developer_name: Field[str] = PydanticField(
        description="Full name of the developer company as written in the agreement."
    )
    agreement_reference: Field[str] = PydanticField(
        description="Notarial deed reference of the development agreement, e.g. 'Rep. A nr 1234/2021'."
    )
    agreement_date: Field[dt.date] = PydanticField(
        description="Date the development agreement was concluded (signed before the notary)."
    )
    price_gross: Field[Decimal] = PydanticField(description="Gross price of the unit in PLN.")
    handover_deadline: Field[dt.date] = PydanticField(description="Contractual deadline to hand over the unit.")
    transfer_deadline: Field[dt.date] = PydanticField(
        description="Contractual deadline to conclude the ownership transfer agreement."
    )
    annex_deadlines: list[Field[AnnexDeadline]] = PydanticField(
        default_factory=list, description="Deadlines changed by annexes."
    )
    penalty_basis: Field[PenaltyBasis]
    penalty_rate: Field[Decimal] = PydanticField(
        description="Daily rate as a fraction (0.0002 = 0.02% per day) or PLN per day for fixed_per_day."
    )
    penalty_cap: Field[PenaltyCap] = PydanticField(description="Cap on the penalty; value null when no cap.")
    penalty_events: Field[list[PenaltyEvent]] = PydanticField(
        description="Delays for which the contractual penalty is due."
    )
    liability_exclusions: list[Field[str]] = PydanticField(
        default_factory=list,
        description="Clauses excluding developer liability; value is a short label, quote the clause.",
    )
    exclusive_penalty_clause: Field[bool] = PydanticField(
        description="True when the buyer may not claim damages exceeding the penalty."
    )
    waiver_of_claims: Field[bool] = PydanticField(
        description="True when the buyer waived claims (usually in the transfer deed)."
    )
    actual_handover_date: Field[dt.date] = PydanticField(description="Actual handover date from the protocol.")
    actual_transfer_date: Field[dt.date] = PydanticField(description="Actual transfer date from the deed.")

    def iter_fields(self) -> list[tuple[str, Field[Any]]]:
        """All Field instances with their JSON paths, e.g. ('annex_deadlines[0]', field)."""
        out: list[tuple[str, Field[Any]]] = []
        for name in type(self).model_fields:
            item = getattr(self, name)
            if isinstance(item, Field):
                out.append((name, item))
            elif isinstance(item, list):
                out.extend((f"{name}[{i}]", f) for i, f in enumerate(item))
        return out


def extraction_json_schema() -> dict[str, Any]:
    """Full schema, including code-owned fields (needs_review)."""
    return Extraction.model_json_schema()


CODE_OWNED_FIELDS = ("needs_review",)
_UNSUPPORTED_KEYS = ("title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                     "multipleOf", "minLength", "maxLength", "pattern", "decimal_places", "max_digits")


def strict_schema(schema: dict[str, Any], drop_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    """Make a Pydantic JSON schema acceptable for structured outputs.

    Every object gets additionalProperties: false and all properties required
    (optional values are expressed as nullable), unsupported constraints are
    removed (Pydantic re-validates them after parsing), and Decimal
    (number | patterned string) becomes a plain number.
    """
    schema = copy.deepcopy(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        any_of = node.get("anyOf")
        if any_of and {"type": "number"} in any_of and any(
            o.get("type") == "string" and "pattern" in o for o in any_of
        ):
            rest = [o for o in any_of if o.get("type") not in ("number", "string")]
            node = {k: v for k, v in node.items() if k != "anyOf"}
            if rest:
                node["anyOf"] = [{"type": "number"}, *rest]
            else:
                node["type"] = "number"
        out = {
            k: ({name: walk(prop) for name, prop in v.items()} if k in ("properties", "$defs") else walk(v))
            for k, v in node.items()
            if k not in _UNSUPPORTED_KEYS
        }
        if out.get("type") == "object" and "properties" in out:
            for name in drop_fields:
                out["properties"].pop(name, None)
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    return walk(schema)


def _field_def(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "value": value,
            "quote": {"type": ["string", "null"]},
            "page": {"type": ["integer", "null"]},
            "document_id": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
        },
        "required": ["value", "quote", "page", "document_id", "confidence"],
    }


# Expected value type per field (the shared definition cannot express it; Pydantic enforces it).
_VALUE_HINTS = {
    "developer_name": "value: developer company name exactly as in the document, or null",
    "agreement_reference": "value: notarial deed number of the development agreement, e.g. 'Rep. A nr 1234/2021', or null",
    "agreement_date": "value: date string YYYY-MM-DD or null",
    "price_gross": "value: JSON number in PLN, e.g. 512340.5, or null",
    "handover_deadline": "value: date string YYYY-MM-DD or null",
    "transfer_deadline": "value: date string YYYY-MM-DD or null",
    "annex_deadlines": "one item per deadline changed by an annex",
    "penalty_basis": "value: one of percent_of_price_per_day, fixed_per_day, statutory_interest, other; or null",
    "penalty_rate": "value: JSON number (daily fraction, e.g. 0.0002, or PLN per day) or null",
    "penalty_cap": "value: {type: percent|amount, value: number} or null",
    "penalty_events": "value: list of handover_delay / transfer_delay, or null",
    "liability_exclusions": "one item per exclusion clause; value: short Polish label (string)",
    "exclusive_penalty_clause": "value: true, false or null",
    "waiver_of_claims": "value: true, false or null",
    "actual_handover_date": "value: date string YYYY-MM-DD or null",
    "actual_transfer_date": "value: date string YYYY-MM-DD or null",
}

# Fields whose value is a list or an object; every other field has a scalar value.
_COMPOSITE = {"penalty_events": "Events", "penalty_cap": "Cap"}
_LISTS = {"annex_deadlines": "Annex", "liability_exclusions": "Field"}


def model_output_json_schema() -> dict[str, Any]:
    """Compact schema given to the model (structured outputs).

    The schema generated from the Pydantic models compiles to a grammar the API rejects as too
    large (one definition per Field[T]). Here all scalar fields share one definition whose value is
    string | number | boolean | null; types, enums and date formats are enforced afterwards by
    Pydantic (Extraction.model_validate), with one retry on invalid output. The JSON shape is
    identical to Extraction, without code-owned fields.
    """
    defs = {
        "Field": _field_def({"type": ["string", "number", "boolean", "null"]}),
        "Events": _field_def({
            "type": ["array", "null"],
            "items": {"type": "string", "enum": [e.value for e in PenaltyEvent]},
        }),
        "Cap": _field_def({"anyOf": [
            {"type": "null"},
            {"type": "object", "additionalProperties": False,
             "properties": {"type": {"type": "string", "enum": ["percent", "amount"]}, "value": {"type": "number"}},
             "required": ["type", "value"]},
        ]}),
        "Annex": _field_def({"anyOf": [
            {"type": "null"},
            {"type": "object", "additionalProperties": False,
             "properties": {
                 "date": {"type": "string"},
                 "field": {"type": "string", "enum": ["handover_deadline", "transfer_deadline"]},
                 "annex_no": {"type": ["integer", "null"]},
             },
             "required": ["date", "field", "annex_no"]},
        ]}),
    }
    properties: dict[str, Any] = {}
    for name in Extraction.model_fields:
        if name in _LISTS:
            properties[name] = {"type": "array", "items": {"$ref": f"#/$defs/{_LISTS[name]}"}}
        else:
            properties[name] = {"$ref": f"#/$defs/{_COMPOSITE.get(name, 'Field')}"}
        properties[name]["description"] = _VALUE_HINTS[name]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
        "$defs": defs,
    }
