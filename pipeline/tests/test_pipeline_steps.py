from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from pipeline.calculate import calculate_from_extraction
from pipeline.classify import classify_documents
from pipeline.documents import Document, render_document
from pipeline.extract import extract_case
from pipeline.llm import LLMError, LLMResponse, call_structured
from pipeline.pdf_text import needs_ocr, read_pdfs
from pipeline.schema import DocumentType, Extraction
from pipeline.settings import load_step
from pipeline.tests.fakes import SETTINGS, FakeLLM, write_pdf
from pipeline.tests.test_schema import minimal_payload
from pipeline.verify_quotes import Issue

PAGES = [
    "UMOWA DEWELOPERSKA zawarta w dniu 10 stycznia 2023 r.",
    "Cena brutto lokalu wynosi 450.000,00 zl.",
    "Deweloper wyda lokal do dnia 31 marca 2024 r.",
    "Kara 0,02% ceny za kazdy dzien opoznienia w wydaniu lokalu.",
]


def payload_matching_pages() -> dict:
    p = minimal_payload()
    p["price_gross"].update(quote="Cena brutto lokalu wynosi 450.000,00 zl.", page=2)
    p["handover_deadline"].update(quote="wyda lokal do dnia 31 marca 2024 r.", page=3)
    for key in ("penalty_basis", "penalty_rate"):
        p[key].update(quote="Kara 0,02% ceny za kazdy dzien", page=4, document_id="doc_1")
    p["penalty_events"].update(quote="opoznienia w wydaniu lokalu", page=4, document_id="doc_1")
    p["actual_handover_date"] = {"value": "2024-05-15", "quote": None, "page": None, "confidence": "high"}
    return p


# --- llm.call_structured ------------------------------------------------------

def test_call_structured_valid_first_time():
    llm = FakeLLM(minimal_payload())
    ex = call_structured(llm, "extract", "c1", SETTINGS, [], [{"type": "text", "text": "x"}], {}, Extraction)
    assert ex.penalty_rate.value == Decimal("0.0002")
    assert len(llm.calls) == 1


def test_call_structured_retries_once_with_feedback():
    bad = minimal_payload()
    bad["handover_deadline"]["value"] = "31.03.2024"
    llm = FakeLLM(bad, minimal_payload())
    call_structured(llm, "extract", "c1", SETTINGS, [], [{"type": "text", "text": "x"}], {}, Extraction)
    retry_messages = llm.calls[1]["messages"]
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    feedback = retry_messages[2]["content"][0]["text"]
    assert "handover_deadline.value" in feedback and "31.03.2024" not in feedback


def test_call_structured_fails_after_second_invalid():
    llm = FakeLLM("not json", "{}")
    with pytest.raises(LLMError) as err:
        call_structured(llm, "extract", "c1", SETTINGS, [], [], {}, Extraction)
    assert err.value.code == "invalid_output"


def test_call_structured_truncated_then_ok():
    llm = FakeLLM(LLMResponse(text='{"price', stop_reason="max_tokens"), minimal_payload())
    call_structured(llm, "extract", "c1", SETTINGS, [], [], {}, Extraction)
    assert len(llm.calls) == 2


def test_call_structured_refusal():
    with pytest.raises(LLMError) as err:
        call_structured(FakeLLM(LLMResponse(text="", stop_reason="refusal")), "x", "c1", SETTINGS, [], [], {},
                        Extraction)
    assert err.value.code == "refusal"


def test_no_document_content_in_logs(caplog):
    caplog.set_level("DEBUG", logger="claims.llm")
    bad = minimal_payload()
    bad["handover_deadline"]["value"] = "SECRET-31.03.2024"
    with pytest.raises(LLMError):
        call_structured(FakeLLM(bad, bad), "extract", "c1", SETTINGS, [], [], {}, Extraction)
    assert "SECRET" not in caplog.text and "450000" not in caplog.text
    assert "case=c1 step=extract" in caplog.text


# --- documents / pdf ------------------------------------------------------------

def test_render_document():
    doc = Document("doc_1", "a.pdf", ["A", "B", "C"], type=DocumentType.ANNEX)
    text = render_document(doc, max_pages=2)
    assert text.startswith('<document id="doc_1" type="annex">')
    assert '<page number="2">\nB\n</page>' in text and "C" not in text
    assert doc.page_count == 3


def test_read_pdfs_with_ocr_fallback(tmp_path):
    a = write_pdf(tmp_path / "a.pdf", ["This page has a proper text layer with enough characters.", ""])
    calls = []

    def fake_ocr(path, page):
        calls.append(page)
        return "ocr text"

    docs = read_pdfs([a], ocr=fake_ocr)
    assert docs[0].id == "doc_1" and docs[0].filename == "a.pdf"
    assert "proper text layer" in docs[0].pages[0]
    assert docs[0].pages[1] == "ocr text" and docs[0].ocr_pages == [2] and calls == [2]


def test_read_pdf_without_ocr_keeps_empty_page(tmp_path):
    a = write_pdf(tmp_path / "a.pdf", [""])
    assert read_pdfs([a])[0].pages == [""]


def test_needs_ocr():
    assert needs_ocr(None) and needs_ocr("  short ") and not needs_ocr("x" * 50)


# --- classify / extract -----------------------------------------------------------

def test_classify_sets_types_and_defaults_missing_to_other():
    docs = [Document("doc_1", "a.pdf", ["UMOWA"]), Document("doc_2", "b.pdf", ["?"])]
    llm = FakeLLM({"documents": [{"document_id": "doc_1", "type": "development_agreement", "confidence": "high"}]})
    out = classify_documents(llm, "c1", docs, SETTINGS)
    assert [d.type for d in docs] == [DocumentType.DEVELOPMENT_AGREEMENT, DocumentType.OTHER]
    assert out[1].confidence == "low"
    schema = llm.calls[0]["schema"]
    assert schema["additionalProperties"] is False


def test_extract_case_verifies_quotes():
    docs = [Document("doc_1", "a.pdf", PAGES)]
    llm = FakeLLM(payload_matching_pages())
    res = extract_case(llm, "c1", docs, SETTINGS)
    assert [(i.path, i.issue) for i in res.issues] == [("actual_handover_date", Issue.QUOTE_MISSING)]
    assert res.extraction.actual_handover_date.needs_review
    assert "needs_review" not in str(llm.calls[0]["schema"])
    assert llm.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_load_step_env_override(monkeypatch):
    monkeypatch.setenv("CLAIMS_MODEL_EXTRACT", "override-model")
    s = load_step("extract")
    assert s.model == "override-model" and s.effort == "high" and s.refusal_fallback
    assert load_step("classify").effort is None


# --- calculate adapter --------------------------------------------------------------

def extraction(**changes) -> Extraction:
    p = payload_matching_pages()
    for k, v in changes.items():
        p[k] = v
    return Extraction.model_validate(p)


def test_calculate_from_extraction_basic():
    # 450 000 zł × 0,02% × 45 dni (01.04–15.05.2024) = 90 zł × 45 = 4 050 zł
    out = calculate_from_extraction(extraction(), dt.date(2025, 1, 1))
    assert out.blocking == []
    assert [p.uncapped_grosze for p in out.result.penalties] == [405_000]


def test_calculate_uses_annex_and_cap_and_flags_review():
    ex = extraction(
        annex_deadlines=[{"value": {"date": "2024-04-30", "field": "handover_deadline", "annex_no": 1},
                          "quote": "q", "page": 1}],
        penalty_cap={"value": {"type": "amount", "value": 1000}, "quote": "q", "page": 1},
        penalty_events={"value": None, "quote": None},
    )
    ex.penalty_rate.needs_review = True
    out = calculate_from_extraction(ex, dt.date(2025, 1, 1))
    handover = out.result.penalties[0]
    # 01.05–15.05 = 15 d × 90 zł = 1 350 zł, cap 1 000 zł
    assert (handover.uncapped_grosze, handover.capped_grosze) == (135_000, 100_000)
    assert any("stawka kary" in w for w in out.warnings)
    assert any("obu zdarzeń" in w for w in out.warnings)
    assert out.result.skipped  # transfer deadline missing


def test_regime_warning_for_old_agreement():
    old = calculate_from_extraction(extraction(agreement_date={"value": "2021-05-14", "quote": "q", "page": 1}),
                                    dt.date(2025, 1, 1))
    assert any("przed 01.07.2022" in w and "niezweryfikowana" in w for w in old.warnings)
    new = calculate_from_extraction(extraction(), dt.date(2025, 1, 1))  # agreement of 10.01.2023
    assert not any("przepisy przejściowe" in w for w in new.warnings)
    unknown = calculate_from_extraction(extraction(agreement_date={"value": None, "quote": None}), dt.date(2025, 1, 1))
    assert any("Nie ustalono daty zawarcia" in w for w in unknown.warnings)


def test_calculate_warns_about_waiver():
    out = calculate_from_extraction(extraction(waiver_of_claims={"value": True, "quote": "q", "page": 1}),
                                    dt.date(2025, 1, 1))
    assert out.result is not None and any("zrzeczeniu" in w for w in out.warnings)


def test_calculate_blocking_without_price_or_basis():
    out = calculate_from_extraction(
        extraction(price_gross={"value": None, "quote": None}, penalty_basis={"value": None, "quote": None}),
        dt.date(2025, 1, 1),
    )
    assert out.result is None and len(out.blocking) == 2


def test_calculate_statutory_interest_with_empty_table_blocks():
    ex = extraction(penalty_basis={"value": "statutory_interest", "quote": "q", "page": 4})
    out = calculate_from_extraction(ex, dt.date(2025, 1, 1))
    assert out.result is None and "statutory_interest.yaml" in out.blocking[0]


def test_calculate_statutory_interest_with_filled_table(tmp_path):
    (tmp_path / "calculator.yaml").write_text(
        "day_count:\n  include_actual_date: true\nstatutory_interest_kind: late_payment\n", encoding="utf-8")
    (tmp_path / "statutory_interest.yaml").write_text(
        "kinds:\n  late_payment:\n    periods:\n"
        "      - {from: 2024-01-01, to: null, rate: '0.10', source: fixture, verified: false}\n",
        encoding="utf-8")
    ex = extraction(penalty_basis={"value": "statutory_interest", "quote": "q", "page": 4},
                    price_gross={"value": 365000, "quote": "q", "page": 2})
    out = calculate_from_extraction(ex, dt.date(2025, 1, 1), config_dir=tmp_path)
    # 36 500 000 gr × 10% × 45/365 = 450 000 gr
    assert out.result.penalties[0].uncapped_grosze == 450_000
