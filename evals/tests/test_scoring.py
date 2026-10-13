from __future__ import annotations

from evals.run_evals import anonymization_gate
from evals.scoring import check_thresholds, field_matches, regressions, score_case, summarize


def field(value, quote="q", needs_review=False):
    return {"value": value, "quote": quote, "page": 1, "document_id": "doc_1", "confidence": "high",
            "needs_review": needs_review}


EMPTY = field(None, None)

EXTRACTION = {
    "developer_name": EMPTY,
    "agreement_reference": EMPTY,
    "agreement_date": field("2021-05-14"),
    "price_gross": field("450000.00"),
    "handover_deadline": field("2024-03-31"),
    "transfer_deadline": EMPTY,
    "annex_deadlines": [field({"date": "2024-06-30", "field": "handover_deadline", "annex_no": 1})],
    "penalty_basis": field("percent_of_price_per_day"),
    "penalty_rate": field("0.00020"),
    "penalty_cap": field({"type": "percent", "value": "0.05"}),
    "penalty_events": field(["transfer_delay", "handover_delay"]),
    "liability_exclusions": [],
    "exclusive_penalty_clause": field(True, needs_review=True),
    "waiver_of_claims": EMPTY,
    "actual_handover_date": EMPTY,
    "actual_transfer_date": field("2024-08-01", quote="nie ma"),
}

EXPECTED = {
    "fields": {
        "agreement_date": "2021-05-14",
        "price_gross": 450000, "handover_deadline": "2024-03-31", "transfer_deadline": None,
        "annex_deadlines": [{"date": "2024-06-30", "field": "handover_deadline", "annex_no": 1}],
        "penalty_basis": "percent_of_price_per_day", "penalty_rate": 0.0002,
        "penalty_cap": {"type": "percent", "value": 0.05},
        "penalty_events": ["handover_delay", "transfer_delay"],
        "exclusive_penalty_clause": True, "waiver_of_claims": None, "actual_handover_date": None,
        "actual_transfer_date": "2024-07-01",
    },
    "clauses": ["penalty-cap-percent", "penalty-exclusive"],
    "penalties_grosze": [450_000],
}


def test_field_matches_normalizes():
    assert field_matches("price_gross", 450000, "450000.00")
    assert field_matches("penalty_rate", 0.0002, "0.00020")
    assert field_matches("penalty_events", ["a", "b"], ["b", "a"])
    assert field_matches("penalty_cap", None, None)
    assert not field_matches("handover_deadline", "2024-03-31", None)


def test_score_and_summary():
    s = score_case("a", EXPECTED, EXTRACTION, [{"path": "actual_transfer_date", "issue": "quote_not_found"}],
                   ["penalty-cap-percent", "jurisdiction-developer-seat"], 42.0, [450_000])
    assert s.field_hits["actual_transfer_date"] is False
    assert sum(s.field_hits.values()) == len(s.field_hits) - 1
    assert (s.clause_tp, s.clause_fn, s.clause_fp) == (1, 1, 1)
    assert s.quotes_unaccounted == 0 and s.quotes_flagged == 2
    assert s.calculator_ok

    summary = summarize([s])
    assert summary["critical_accuracy"] == 1.0
    assert summary["clause_recall"] == 0.5 and summary["clause_false_alarm_rate"] == 0.5
    assert summary["failed_fields"] == ["a:actual_transfer_date"]
    failures = check_thresholds(summary)
    assert any(f.startswith("other_accuracy") for f in failures)
    assert any(f.startswith("clause_recall") for f in failures)
    assert not any(f.startswith("critical_accuracy") for f in failures)


def test_regressions():
    assert regressions({"per_field": {"a": 0.9}}, {"per_field": {"a": 1.0}}) == ["a: 1.000 → 0.900"]
    assert regressions({"per_field": {"a": 1.0}}, None) == []


def test_anonymization_gate_has_no_leaks():
    assert anonymization_gate() == []
