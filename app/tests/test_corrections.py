from decimal import Decimal

import pytest

from app.corrections import CorrectionError, amount_in_quote, parse_decimal, value_matches_quote


@pytest.mark.parametrize("raw, expected", [
    ("1.080.000,00", "1080000.00"), ("1 080 000,00 zł", "1080000.00"), ("1\u00a0080\u00a0000,00", "1080000.00"),
    ("1080000,00", "1080000.00"), ("1080000.5", "1080000.5"), ("0,0001", "0.0001"), ("1.080.000", "1080000"),
])
def test_parse_polish_numbers(raw, expected):
    assert parse_decimal(raw) == Decimal(expected)


def test_parse_invalid():
    with pytest.raises(CorrectionError):
        parse_decimal("abc")


def test_value_matches_quote():
    quote = "za cenę w kwocie brutto 1.080.000,00 zł (jeden milion osiemdziesiąt tysięcy złotych)"
    assert value_matches_quote("price_gross", "1080000", quote) is True
    assert value_matches_quote("price_gross", "108000000", quote) is False
    rate_quote = "kary umownej w wysokości 0,01 % ceny za każdy dzień opóźnienia"
    assert value_matches_quote("penalty_rate", "0.0001", rate_quote) is True
    assert value_matches_quote("penalty_rate", "0.001", rate_quote) is False
    assert value_matches_quote("penalty_cap", {"type": "percent", "value": "0.05"}, "nie więcej niż 5% ceny") is True
    assert value_matches_quote("price_gross", "1", "brak liczb") is None
    assert value_matches_quote("price_gross", None, quote) is None
    assert value_matches_quote("actual_handover_date", "2026-09-01", quote) is None


def test_amount_in_quote():
    assert amount_in_quote("za cenę w kwocie brutto 1.080.000,00 zł (jeden milion)") == Decimal("1080000.00")
    assert amount_in_quote("cena 500.000,00 zł, w tym VAT 37.037,04 zł") is None  # two amounts
    assert amount_in_quote("0,01 % ceny") is None
    assert amount_in_quote(None) is None


def test_old_extraction_without_new_fields_still_loads():
    from app.corrections import apply_corrections
    from pipeline.tests.test_schema import minimal_payload

    old = minimal_payload()
    for name in ("developer_name", "agreement_reference", "annex_deadlines"):
        old.pop(name, None)
    ex = apply_corrections(old, {})
    assert ex.developer_name.value is None and ex.annex_deadlines == []
