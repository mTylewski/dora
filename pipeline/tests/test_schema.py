from __future__ import annotations

import datetime as dt
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.schema import Extraction, model_output_json_schema

ROOT = Path(__file__).resolve().parents[2]


def _load_export_script():
    spec = importlib.util.spec_from_file_location("export_schemas", ROOT / "scripts" / "export_schemas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def empty(**kw):
    return {"value": None, "quote": None, **kw}


def minimal_payload() -> dict:
    return {
        "developer_name": empty(),
        "agreement_reference": empty(),
        "agreement_date": {"value": "2023-01-10", "quote": "zawarta w dniu 10 stycznia 2023 r.", "page": 1,
                           "document_id": "doc_1", "confidence": "high"},
        "price_gross": {"value": "450000.00", "quote": "cena brutto 450.000,00 zł", "page": 2,
                        "document_id": "doc_1", "confidence": "high"},
        "handover_deadline": {"value": "2024-03-31", "quote": "do dnia 31 marca 2024 r.", "page": 3,
                              "document_id": "doc_1", "confidence": "high"},
        "transfer_deadline": empty(),
        "penalty_basis": {"value": "percent_of_price_per_day", "quote": "0,02% ceny za każdy dzień", "page": 5,
                          "confidence": "high"},
        "penalty_rate": {"value": 0.0002, "quote": "0,02% ceny za każdy dzień", "page": 5, "confidence": "high"},
        "penalty_cap": empty(),
        "penalty_events": {"value": ["handover_delay"], "quote": "za opóźnienie w wydaniu lokalu", "page": 5,
                           "confidence": "high"},
        "exclusive_penalty_clause": empty(),
        "waiver_of_claims": empty(),
        "actual_handover_date": empty(),
        "actual_transfer_date": empty(),
    }


def test_committed_schemas_are_up_to_date():
    module = _load_export_script()
    for name, fn in module.TARGETS.items():
        committed = (ROOT / name).read_text(encoding="utf-8")
        assert committed == module.render(fn), f"run scripts/export_schemas.py ({name} is stale)"


def test_model_output_schema_has_no_needs_review():
    assert "needs_review" not in str(model_output_json_schema())


def test_parse_minimal_payload():
    ex = Extraction.model_validate(minimal_payload())
    assert ex.price_gross.value == Decimal("450000.00")
    assert ex.handover_deadline.value == dt.date(2024, 3, 31)
    assert ex.penalty_rate.value == Decimal("0.0002")
    assert ex.annex_deadlines == [] and ex.liability_exclusions == []


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal_payload() | {"surprise": 1})


def test_bad_enum_rejected():
    payload = minimal_payload()
    payload["penalty_basis"]["value"] = "per_week"
    with pytest.raises(ValidationError):
        Extraction.model_validate(payload)


def test_iter_fields_includes_list_items():
    payload = minimal_payload()
    payload["annex_deadlines"] = [{"value": {"date": "2024-06-30", "field": "handover_deadline", "annex_no": 1},
                                   "quote": "termin zmienia się na 30 czerwca 2024", "page": 1,
                                   "document_id": "doc_2"}]
    payload["liability_exclusions"] = [{"value": "siła wyższa", "quote": "z przyczyn siły wyższej", "page": 6}]
    paths = [p for p, _ in Extraction.model_validate(payload).iter_fields()]
    assert "annex_deadlines[0]" in paths and "liability_exclusions[0]" in paths
    assert len(paths) == 16


def test_model_output_schema_covers_every_extraction_field():
    schema = model_output_json_schema()
    assert list(schema["properties"]) == list(Extraction.model_fields)
    # compact: few shared definitions (the API rejects large compiled grammars)
    assert len(schema["$defs"]) <= 4
