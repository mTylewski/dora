"""Calculator tests. Every expected amount is calculated by hand in the comment above it.

Rate tables used here are synthetic test fixtures, not real statutory rates.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from calculator.case import CaseInput, build_timeline, calculate_case, load_calc_config
from calculator.core import (
    Amendment,
    Basis,
    CalcConfig,
    CalculationError,
    Cap,
    EffectiveDeadline,
    Event,
    Terms,
    compute_penalty,
    delay_period,
    effective_deadline,
    fmt_percent,
    statutory_interest,
)
from calculator.money import format_pln, pln_to_grosze, round_grosze
from calculator.rates import RatePeriod, RateTable, RateTableError, load_rate_table, parse_rate_table

D = dt.date
INCL = CalcConfig(include_actual_date=True)
EXCL = CalcConfig(include_actual_date=False)
INCL_VERIFIED = CalcConfig(include_actual_date=True, verified=True)

PRICE_500K = pln_to_grosze("500000.00")  # 50 000 000 gr
PCT_002 = Terms(Basis.PERCENT_OF_PRICE_PER_DAY, PRICE_500K, Decimal("0.0002"))


def penalty(terms=PCT_002, deadline=D(2024, 3, 31), actual=D(2024, 5, 15), amendments=(), config=INCL, as_of=D(2025, 1, 1)):
    return compute_penalty(Event.HANDOVER_DELAY, deadline, list(amendments), actual, as_of, terms, config)


# --- money -------------------------------------------------------------------

def test_pln_to_grosze():
    assert pln_to_grosze("1234.56") == 123456
    assert pln_to_grosze(Decimal("10")) == 1000
    assert pln_to_grosze(7) == 700


def test_pln_to_grosze_rejects_float_and_sub_grosz():
    with pytest.raises(TypeError):
        pln_to_grosze(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        pln_to_grosze("1.005")


def test_round_grosze_half_up():
    assert round_grosze(Decimal("12.5")) == 13
    assert round_grosze(Decimal("12.4999")) == 12


def test_format_pln():
    assert format_pln(123456789) == "1 234 567,89 zł"
    assert format_pln(5) == "0,05 zł"
    assert format_pln(-150) == "-1,50 zł"


def test_fmt_percent():
    assert fmt_percent(Decimal("0.0002")) == "0,02%"
    assert fmt_percent(Decimal("0.05")) == "5%"


# --- days --------------------------------------------------------------------

def test_delay_inclusive():
    # deadline 31.03.2024 -> delay from 01.04 to 15.05 inclusive: 30 (April) + 15 = 45
    assert delay_period(D(2024, 3, 31), D(2024, 5, 15), INCL) == (D(2024, 4, 1), D(2024, 5, 15), 45)


def test_delay_exclusive():
    # same, without 15.05: 44 days
    assert delay_period(D(2024, 3, 31), D(2024, 5, 15), EXCL) == (D(2024, 4, 1), D(2024, 5, 14), 44)


def test_delay_over_leap_day():
    # deadline 28.02.2024, actual 01.03.2024 inclusive: 29.02 + 01.03 = 2
    assert delay_period(D(2024, 2, 28), D(2024, 3, 1), INCL)[2] == 2


@pytest.mark.parametrize("actual", [D(2024, 3, 31), D(2024, 3, 1)])
def test_no_delay_on_or_before_deadline(actual):
    assert delay_period(D(2024, 3, 31), actual, INCL)[2] == 0


def test_actual_day_after_deadline_exclusive_is_zero():
    # deadline 31.03, actual 01.04, actual day not counted -> 0
    assert delay_period(D(2024, 3, 31), D(2024, 4, 1), EXCL)[2] == 0


# --- effective deadline --------------------------------------------------------

def test_effective_deadline_contract():
    assert effective_deadline(D(2024, 3, 31), []) == EffectiveDeadline(D(2024, 3, 31), "contract")


def test_effective_deadline_latest_numbered_annex_wins_regardless_of_order():
    amendments = [Amendment(D(2024, 9, 30), 2), Amendment(D(2024, 6, 30), 1)]
    assert effective_deadline(D(2024, 3, 31), amendments) == EffectiveDeadline(D(2024, 9, 30), "annex", 2)


def test_effective_deadline_annex_wins_even_if_earlier_than_contract():
    assert effective_deadline(D(2024, 3, 31), [Amendment(D(2024, 2, 1), 1)]).deadline == D(2024, 2, 1)


def test_effective_deadline_unnumbered_keeps_document_order():
    amendments = [Amendment(D(2024, 9, 30), None), Amendment(D(2024, 6, 30), 3)]
    assert effective_deadline(None, amendments) == EffectiveDeadline(D(2024, 6, 30), "annex", 3)


def test_effective_deadline_missing():
    with pytest.raises(CalculationError):
        effective_deadline(None, [])


def test_effective_deadline_describe():
    assert EffectiveDeadline(D(2024, 1, 1), "contract").describe() == "umowa"
    assert EffectiveDeadline(D(2024, 1, 1), "annex", 2).describe() == "aneks nr 2"
    assert EffectiveDeadline(D(2024, 1, 1), "annex").describe() == "aneks (bez numeru)"


# --- penalty amounts ------------------------------------------------------------

def test_percent_of_price_inclusive():
    # 500 000,00 zł × 0,02% × 45 dni = 100 zł × 45 = 4 500,00 zł
    r = penalty()
    assert r.days == 45
    assert r.uncapped_grosze == r.capped_grosze == 450_000
    assert r.cap_grosze is None and not r.cap_reached and not r.ongoing
    assert r.steps[-1].result == format_pln(450_000)
    assert any("nie został potwierdzony" in w for w in r.warnings)


def test_percent_of_price_exclusive():
    # 100 zł × 44 dni = 4 400,00 zł
    assert penalty(config=EXCL).uncapped_grosze == 440_000


def test_verified_config_has_no_day_count_warning():
    assert penalty(config=INCL_VERIFIED).warnings == []


def test_rounding_once_on_final_amount():
    # 412 345,67 zł = 41 234 567 gr × 0,0001 × 3 = 12 370,3701 gr -> 12 370 gr
    terms = Terms(Basis.PERCENT_OF_PRICE_PER_DAY, pln_to_grosze("412345.67"), Decimal("0.0001"))
    assert penalty(terms, D(2024, 1, 1), D(2024, 1, 4)).uncapped_grosze == 12_370


def test_annex_deadline_used():
    # annex 2 moves deadline to 30.09.2024; actual 10.10.2024 -> 10 days × 100 zł = 1 000,00 zł
    amendments = [Amendment(D(2024, 6, 30), 1), Amendment(D(2024, 9, 30), 2)]
    r = penalty(actual=D(2024, 10, 10), amendments=amendments)
    assert (r.days, r.uncapped_grosze) == (10, 100_000)
    assert r.effective_deadline.annex_no == 2
    assert "aneks nr 2" in r.steps[0].formula


def test_fixed_per_day():
    # 50 zł × 45 dni = 2 250,00 zł
    terms = Terms(Basis.FIXED_PER_DAY, PRICE_500K, Decimal("50"))
    assert penalty(terms).uncapped_grosze == 225_000


def test_fixed_per_day_half_up():
    # 0,125 zł × 1 dzień = 12,5 gr -> 13 gr (half up; half even would give 12)
    terms = Terms(Basis.FIXED_PER_DAY, PRICE_500K, Decimal("0.125"))
    assert penalty(terms, D(2024, 1, 1), D(2024, 1, 2)).uncapped_grosze == 13


def test_percent_cap_reached():
    # 500 000 zł × 0,1% × 200 dni = 500 zł × 200 = 100 000 zł; cap 5% = 25 000 zł
    terms = Terms(Basis.PERCENT_OF_PRICE_PER_DAY, PRICE_500K, Decimal("0.001"), Cap("percent", Decimal("0.05")))
    r = penalty(terms, D(2024, 1, 1), D(2024, 7, 19))  # 02.01–19.07.2024 = 200 days
    assert r.days == 200
    assert r.uncapped_grosze == 10_000_000
    assert r.cap_grosze == 2_500_000
    assert r.capped_grosze == 2_500_000
    assert r.cap_reached
    assert any("abuzywna" in w for w in r.warnings)


def test_amount_cap_not_reached():
    # 4 500 zł < cap 10 000 zł
    terms = Terms(Basis.PERCENT_OF_PRICE_PER_DAY, PRICE_500K, Decimal("0.0002"), Cap("amount", Decimal("10000")))
    r = penalty(terms)
    assert (r.uncapped_grosze, r.cap_grosze, r.capped_grosze, r.cap_reached) == (450_000, 1_000_000, 450_000, False)
    assert r.steps[-2].formula == "kwota wskazana w umowie"


def test_unknown_cap_type():
    terms = Terms(Basis.PERCENT_OF_PRICE_PER_DAY, PRICE_500K, Decimal("0.0002"), Cap("weird", Decimal("1")))
    with pytest.raises(CalculationError):
        penalty(terms)


def test_missing_rate():
    with pytest.raises(CalculationError):
        penalty(Terms(Basis.PERCENT_OF_PRICE_PER_DAY, PRICE_500K))


def test_other_basis_returns_no_amount():
    r = penalty(Terms(Basis.OTHER, PRICE_500K))
    assert r.uncapped_grosze is None and r.capped_grosze is None and not r.cap_reached
    assert any("ręcznego" in w for w in r.warnings)


def test_ongoing_delay_uses_as_of():
    # no actual date, as of 10.04.2024 -> 01.04–10.04 = 10 days × 100 zł
    r = penalty(actual=None, as_of=D(2024, 4, 10))
    assert r.ongoing and r.days == 10 and r.uncapped_grosze == 100_000
    assert any("opóźnienie liczone na dzień 10.04.2024" in w for w in r.warnings)
    assert "opóźnienie trwa" in r.steps[1].formula


def test_not_late_is_zero():
    assert penalty(actual=D(2024, 3, 1)).uncapped_grosze == 0


# --- statutory interest ------------------------------------------------------------

TEST_TABLE = RateTable("test", (
    RatePeriod(D(2024, 7, 1), None, Decimal("0.12"), "fixture B", False),
    RatePeriod(D(2024, 1, 1), D(2024, 6, 30), Decimal("0.10"), "fixture A", True),
))
VERIFIED_TABLE = RateTable("test", (RatePeriod(D(2024, 1, 1), None, Decimal("0.10"), "fixture", True),))


def test_statutory_interest_split_by_periods():
    # 365 000 zł = 36 500 000 gr
    # 21.06–30.06 (10 d): 36 500 000 × 10% × 10/365 = 100 000 gr
    # 01.07–10.07 (10 d): 36 500 000 × 12% × 10/365 = 120 000 gr
    res = statutory_interest(36_500_000, D(2024, 6, 21), D(2024, 7, 10), TEST_TABLE, INCL)
    assert res.grosze == 220_000
    assert [s.days for s in res.segments] == [10, 10]
    assert not res.all_rates_verified


def test_statutory_interest_empty_range():
    res = statutory_interest(100, D(2024, 2, 2), D(2024, 2, 1), TEST_TABLE, INCL)
    assert res.grosze == 0 and res.segments == () and not res.all_rates_verified


def test_statutory_interest_basis_in_penalty():
    terms = Terms(Basis.STATUTORY_INTEREST, 36_500_000, interest_table=TEST_TABLE)
    r = penalty(terms, D(2024, 6, 20), D(2024, 7, 10))
    assert r.uncapped_grosze == 220_000
    assert r.steps[-1].label == "Suma odsetek"
    assert any("odsetek nie są oznaczone" in w for w in r.warnings)


def test_statutory_interest_verified_rates_and_missing_source():
    table = RateTable("t", (RatePeriod(D(2024, 1, 1), None, Decimal("0.10"), "", True),))
    terms = Terms(Basis.STATUTORY_INTEREST, 36_500_000, interest_table=table)
    # 02.01–11.01 = 10 d: 36 500 000 × 10% × 10/365 = 100 000 gr
    r = penalty(terms, D(2024, 1, 1), D(2024, 1, 11), config=INCL_VERIFIED)
    assert r.uncapped_grosze == 100_000
    assert r.warnings == []
    assert r.steps[2].result == "brak źródła stawki"


def test_statutory_interest_requires_table():
    with pytest.raises(CalculationError):
        penalty(Terms(Basis.STATUTORY_INTEREST, PRICE_500K))


def test_rate_table_gap_raises():
    table = RateTable("t", (RatePeriod(D(2024, 1, 1), D(2024, 1, 31), Decimal("0.1"), "", True),))
    with pytest.raises(RateTableError):
        table.rate_for(D(2024, 2, 1))


def test_rate_table_overlap_raises():
    with pytest.raises(RateTableError):
        RateTable("t", (
            RatePeriod(D(2024, 1, 1), D(2024, 2, 15), Decimal("0.1"), "", True),
            RatePeriod(D(2024, 2, 1), None, Decimal("0.1"), "", True),
        ))
    with pytest.raises(RateTableError):
        RateTable("t", (
            RatePeriod(D(2024, 1, 1), None, Decimal("0.1"), "", True),
            RatePeriod(D(2024, 2, 1), None, Decimal("0.1"), "", True),
        ))


def test_parse_rate_table():
    data = {"kinds": {"late": {"periods": [
        {"from": "2024-01-01", "to": "2024-06-30", "rate": "0.10", "source": "x", "verified": True},
        {"from": D(2024, 7, 1), "to": None, "rate": "0.12"},
    ]}}}
    table = parse_rate_table(data, "late")
    assert [p.rate for p in table.periods] == [Decimal("0.10"), Decimal("0.12")]
    assert table.periods[1].source == "" and not table.periods[1].verified
    assert not table.all_verified


def test_parse_rate_table_errors():
    with pytest.raises(RateTableError):
        parse_rate_table({"kinds": {}}, "late")
    with pytest.raises(RateTableError):
        parse_rate_table({"kinds": {"late": {"periods": [{"from": "2024-01-01", "rate": 0.1}]}}}, "late")
    with pytest.raises(RateTableError):
        parse_rate_table({"kinds": {"late": {"periods": [{"rate": "0.1"}]}}}, "late")


def test_repo_rate_table_loads_and_is_empty_until_filled():
    path = Path(__file__).resolve().parents[2] / "config" / "statutory_interest.yaml"
    for kind in ("statutory", "late_payment"):
        table = load_rate_table(path, kind)
        assert table.kind == kind
        for p in table.periods:  # filled tables must cite a source
            assert p.source


# --- case level ---------------------------------------------------------------------

def make_case(**overrides):
    base = dict(
        terms=PCT_002,
        penalty_events=(Event.HANDOVER_DELAY, Event.TRANSFER_DELAY),
        as_of=D(2025, 1, 1),
        handover_deadline=D(2024, 3, 31),
        transfer_deadline=D(2024, 6, 30),
        handover_amendments=(Amendment(D(2024, 4, 30), 1),),
        actual_handover_date=D(2024, 5, 15),
        actual_transfer_date=D(2024, 7, 10),
    )
    base.update(overrides)
    return CaseInput(**base)


def test_calculate_case_both_events():
    # handover: annex 30.04 -> 01.05–15.05 = 15 d × 100 zł = 1 500 zł
    # transfer: 01.07–10.07 = 10 d × 100 zł = 1 000 zł
    res = calculate_case(make_case(), INCL)
    assert [p.uncapped_grosze for p in res.penalties] == [150_000, 100_000]
    assert res.total_uncapped_grosze == res.total_capped_grosze == 250_000
    assert res.skipped == []


def test_calculate_case_only_listed_events_and_skips_missing_deadline():
    res = calculate_case(make_case(penalty_events=(Event.TRANSFER_DELAY,), transfer_deadline=None), INCL)
    assert res.penalties == []
    assert res.skipped == ["opóźnienie w zawarciu umowy przenoszącej własność: brak terminu w umowie i w aneksach"]


def test_case_totals_ignore_other_basis():
    res = calculate_case(make_case(terms=Terms(Basis.OTHER, PRICE_500K)), INCL)
    assert res.total_uncapped_grosze == 0 and res.total_capped_grosze == 0


def test_timeline_sorted_with_all_entries():
    case = make_case(transfer_amendments=(Amendment(D(2024, 8, 31), None),))
    kinds = [(e.date, e.kind) for e in build_timeline(case)]
    assert kinds == sorted(kinds, key=lambda k: k[0])
    labels = [e.label for e in build_timeline(case)]
    assert "Termin wydania lokalu (aneks nr 1)" in labels
    assert "Termin umowy przenoszącej (aneks bez numeru)" in labels


def test_timeline_minimal():
    case = CaseInput(terms=PCT_002, penalty_events=(), as_of=D(2025, 1, 1))
    assert [e.kind for e in build_timeline(case)] == ["as_of"]


def test_load_calc_config_repo_file():
    path = Path(__file__).resolve().parents[2] / "config" / "calculator.yaml"
    cfg = load_calc_config(path)
    assert isinstance(cfg.include_actual_date, bool)
    assert cfg.interest_year_days == 365


def test_load_calc_config_rejects_missing_choice(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("day_count:\n  include_actual_date: null\n", encoding="utf-8")
    with pytest.raises(CalculationError):
        load_calc_config(p)
