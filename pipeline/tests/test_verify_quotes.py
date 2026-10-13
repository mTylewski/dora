from __future__ import annotations

from pipeline.schema import Extraction, Field
from pipeline.tests.test_schema import minimal_payload
from pipeline.verify_quotes import DocumentText, Issue, normalize, verify_extraction, verify_field

PAGES = [
    "UMOWA DEWELOPERSKA zawarta w dniu 10 stycznia 2023 r.\nStrony ustalają",
    "§ 3. Cena brutto lokalu wynosi\n450.000,00 zł  (słownie: czterysta pięćdziesiąt tysięcy)",
    "Deweloper zobowiązuje się wydać lokal do dnia 31 marca 2024 r.",
    "",
    "W przypadku opóźnienia Deweloper zapłaci karę w wysokości 0,02% ceny za każdy dzień opóź-\nnienia, "
    "za opóźnienie w wydaniu lokalu. Kara nie może przekroczyć „5% ceny” – łącznie.",
    "Przyczyny niezależne od Dewelopera, w tym siła wyższa, wyłączają",
    "jego odpowiedzialność za opóźnienie.",
]
DOCS = {"doc_1": DocumentText(PAGES)}


def f(quote, page=None, value="x", document_id="doc_1", confidence="high"):
    return Field[str](value=value, quote=quote, page=page, document_id=document_id, confidence=confidence)


def test_normalize():
    assert normalize("  a  b\n\tc ") == "a b c"
    assert normalize("„x” – y") == '"x" - y'
    assert normalize("ko­rzyść") == "korzyść"
    assert normalize("opóź-\nnienia", join_hyphenation=True) == "opóźnienia"


def test_found_on_stated_page_with_whitespace_differences():
    field = f("Cena brutto lokalu wynosi 450.000,00 zł", page=2)
    assert verify_field("price", field, DOCS) == []
    assert field.needs_review is False


def test_typographic_quotes_and_dashes():
    assert verify_field("cap", f('"5% ceny" - łącznie', page=5), DOCS) == []


def test_hyphenated_line_break():
    assert verify_field("rate", f("0,02% ceny za każdy dzień opóźnienia", page=5), DOCS) == []


def test_quote_across_page_break_starts_on_stated_page():
    assert verify_field("excl", f("siła wyższa, wyłączają jego odpowiedzialność", page=6), DOCS) == []


def test_not_found():
    field = f("kara 0,05% dziennie", page=5)
    assert verify_field("rate", field, DOCS)[0].issue is Issue.QUOTE_NOT_FOUND
    assert field.needs_review is True


def test_page_mismatch_reports_found_page():
    issue = verify_field("deadline", f("do dnia 31 marca 2024 r.", page=4), DOCS)[0]
    assert (issue.issue, issue.found_page) == (Issue.PAGE_MISMATCH, 3)


def test_page_missing():
    issue = verify_field("deadline", f("do dnia 31 marca 2024 r."), DOCS)[0]
    assert (issue.issue, issue.found_page) == (Issue.PAGE_MISSING, 3)


def test_value_without_quote():
    assert verify_field("x", f(None), DOCS)[0].issue is Issue.QUOTE_MISSING


def test_blank_quote_is_missing():
    assert verify_field("x", f("   ", page=1), DOCS)[0].issue is Issue.QUOTE_NOT_FOUND


def test_unknown_document():
    assert verify_field("x", f("UMOWA", page=1, document_id="doc_9"), DOCS)[0].issue is Issue.UNKNOWN_DOCUMENT


def test_single_document_without_id_is_used():
    assert verify_field("x", f("UMOWA DEWELOPERSKA", page=1, document_id=None), DOCS) == []


def test_low_confidence_flags_review():
    field = f("UMOWA DEWELOPERSKA", page=1, confidence="low")
    assert [i.issue for i in verify_field("x", field, DOCS)] == [Issue.LOW_CONFIDENCE]
    assert field.needs_review


def test_null_field_is_clean_and_resets_model_flag():
    field = Field[str](value=None, quote=None, needs_review=True)
    assert verify_field("x", field, DOCS) == [] and field.needs_review is False


def test_verify_extraction_end_to_end():
    payload = minimal_payload()
    payload["price_gross"]["quote"] = "Cena brutto lokalu wynosi 450.000,00 zł"
    payload["handover_deadline"]["quote"] = "wydać lokal do dnia 31 marca 2024 r."
    payload["penalty_basis"]["quote"] = "karę w wysokości 0,02% ceny za każdy dzień opóźnienia"
    payload["penalty_rate"]["quote"] = "0,02% ceny za każdy dzień"
    for key in ("penalty_basis", "penalty_rate", "penalty_events"):
        payload[key]["document_id"] = "doc_1"
    payload["penalty_rate"]["page"] = 2  # wrong page
    ex = Extraction.model_validate(payload)
    issues = verify_extraction(ex, {"doc_1": PAGES})
    assert [(i.path, i.issue) for i in issues] == [("penalty_rate", Issue.PAGE_MISMATCH)]
    assert ex.penalty_rate.needs_review and not ex.price_gross.needs_review


def test_quote_without_value_is_unresolved():
    field = f("Deweloper zobowiązuje się wydać lokal", page=3, value=None, confidence="low")
    assert [i.issue for i in verify_field("x", field, DOCS)] == [Issue.VALUE_UNRESOLVED, Issue.LOW_CONFIDENCE]
    assert field.needs_review
