from __future__ import annotations

import datetime as dt
import json

from pipeline.run import analysis_to_dict, analyze_case, prepare_case
from pipeline.tests.fakes import FakeLLM, write_pdf
from pipeline.tests.test_anonymize import PESEL

PAGES = [
    f"UMOWA DEWELOPERSKA z Panem Jan Nowakowski PESEL {PESEL}",
    "Cena brutto lokalu wynosi 450.000,00 zl.",
    "Deweloper wyda lokal do dnia 31 marca 2024 r.",
    "Kara 0,02% ceny za kazdy dzien opoznienia w wydaniu lokalu.",
]


def extraction_payload():
    def f(value, quote, page):
        return {"value": value, "quote": quote, "page": page, "document_id": "doc_1", "confidence": "high"}

    empty = {"value": None, "quote": None, "page": None, "document_id": None, "confidence": "high"}
    return {
        "developer_name": f("APM Test sp. z o.o.", "UMOWA DEWELOPERSKA", 1),
        "agreement_reference": empty,
        "agreement_date": empty,
        "price_gross": f(450000, "Cena brutto lokalu wynosi 450.000,00 zl.", 2),
        "handover_deadline": f("2024-03-31", "wyda lokal do dnia 31 marca 2024 r.", 3),
        "transfer_deadline": empty,
        "annex_deadlines": [],
        "penalty_basis": f("percent_of_price_per_day", "Kara 0,02% ceny za kazdy dzien", 4),
        "penalty_rate": f(0.0002, "Kara 0,02% ceny za kazdy dzien", 4),
        "penalty_cap": empty,
        "penalty_events": f(["handover_delay"], "opoznienia w wydaniu lokalu", 4),
        "liability_exclusions": [],
        "exclusive_penalty_clause": empty,
        "waiver_of_claims": empty,
        "actual_handover_date": empty,
        "actual_transfer_date": empty,
    }


def test_prepare_and_analyze_end_to_end(tmp_path):
    pdf = write_pdf(tmp_path / "umowa.pdf", PAGES)
    prepared = prepare_case("case1", [pdf])

    # Anonymized text contains no personal data; originals are untouched
    anon_text = " ".join(prepared.anonymized[0].pages)
    assert PESEL not in anon_text and "Nowakowski" not in anon_text
    assert PESEL in prepared.originals[0].pages[0]
    assert {r["label"] for r in prepared.replacements} >= {"PESEL", "OSOBA"}

    llm = FakeLLM(
        {"documents": [{"document_id": "doc_1", "type": "development_agreement", "confidence": "high"}]},
        extraction_payload(),
        {"flags": [{"clause_id": "penalty-symbolic-rate", "quote": "UMOWA DEWELOPERSKA z Panem [OSOBA_1]",
                    "page": 1, "document_id": "doc_1", "reasoning": "Dotyczy [OSOBA_1].", "confidence": "low"}]},
    )
    analysis = analyze_case(llm, prepared, dt.date(2024, 4, 10))

    # Nothing personal was sent to the model
    sent = json.dumps([c["messages"] for c in llm.calls], ensure_ascii=False, default=str)
    assert PESEL not in sent and "Nowakowski" not in sent
    assert prepared.originals[0].type == "development_agreement"

    # Ongoing delay: 01.04–10.04.2024 = 10 days × 90 zł
    penalty = analysis.calculation.result.penalties[0]
    assert penalty.ongoing and penalty.uncapped_grosze == 90_000
    assert analysis.clauses.flags[0].needs_review is False
    assert set(analysis.timings_ms) == {"classify", "extract", "clauses", "calculate"}

    data = analysis_to_dict(analysis, prepared.mapping)
    json.dumps(data)  # serializable
    assert data["clauses"][0]["quote"].endswith("Jan Nowakowski")
    assert "Jan Nowakowski" in data["clauses"][0]["reasoning"]
    price = next(f for f in data["fields"] if f["path"] == "price_gross")
    assert price["value"] == "450000"
    assert data["calculation"]["result"]["penalties"][0]["cap_reached"] is False

    # Without mapping, quotes stay anonymized
    assert "[OSOBA_1]" in analysis_to_dict(analysis)["clauses"][0]["quote"]


def test_prepare_without_anonymization(tmp_path):
    pdf = write_pdf(tmp_path / "a.pdf", PAGES[:1])
    prepared = prepare_case("c", [pdf], anonymize=False)
    assert PESEL in prepared.anonymized[0].pages[0] and prepared.mapping == {}


def test_progress_callbacks(tmp_path):
    pdf = write_pdf(tmp_path / "a.pdf", PAGES)
    seen = []
    prepared = prepare_case("c", [pdf], progress=lambda text, pct: seen.append((text, pct)))
    assert seen[0] == ("Dokument 1 z 1 — odczyt: strona 1 z 4", 26)
    assert seen[-1] == ("Anonimizacja danych osobowych", 92)
    assert [p for _, p in seen] == sorted(p for _, p in seen)

    steps = []
    llm = FakeLLM(
        {"documents": [{"document_id": "doc_1", "type": "development_agreement", "confidence": "high"}]},
        extraction_payload(), {"flags": []},
    )
    analyze_case(llm, prepared, dt.date(2024, 4, 10), progress=lambda text, pct: steps.append(pct))
    assert steps == [5, 15, 55, 95]
