"""Step 5: map the verified extraction onto the deterministic calculator."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from calculator.case import CaseInput, CaseResult, calculate_case, load_calc_config
from calculator.core import Amendment, Basis, Cap, Event, Terms
from calculator.money import round_grosze
from calculator.rates import load_rate_table
from pipeline.schema import Extraction
from pipeline.settings import CONFIG_DIR

FIELD_LABELS = {
    "agreement_date": "data zawarcia umowy",
    "price_gross": "cena",
    "handover_deadline": "termin wydania lokalu",
    "transfer_deadline": "termin umowy przenoszącej",
    "penalty_basis": "sposób naliczania kary",
    "penalty_rate": "stawka kary",
    "penalty_cap": "limit kary",
    "penalty_events": "zdarzenia objęte karą",
    "actual_handover_date": "data wydania lokalu",
    "actual_transfer_date": "data umowy przenoszącej",
}


@dataclass
class CalculationOutcome:
    result: CaseResult | None
    blocking: list[str] = field(default_factory=list)  # why no calculation was possible
    warnings: list[str] = field(default_factory=list)


def regime_warnings(ex: Extraction, calc_cfg_path: Path) -> list[str]:
    """Flag agreements concluded before the new development act (date from config, to be verified)."""
    with calc_cfg_path.open(encoding="utf-8") as fh:
        regime = (yaml.safe_load(fh) or {}).get("development_act")
    if not regime or not regime.get("new_act_from"):
        return []
    boundary = regime["new_act_from"]
    if not isinstance(boundary, dt.date):
        boundary = dt.date.fromisoformat(str(boundary))
    signed = ex.agreement_date.value
    if signed is None:
        return ["Nie ustalono daty zawarcia umowy deweloperskiej — sprawdź, której ustawy dotyczy umowa."]
    if signed < boundary:
        note = "" if regime.get("verified") else " (data graniczna niezweryfikowana w config/calculator.yaml)"
        return [f"Umowa zawarta {signed:%d.%m.%Y}, przed {boundary:%d.%m.%Y} — "
                f"sprawdź przepisy przejściowe ustawy deweloperskiej{note}."]
    return []


def calculate_from_extraction(
    ex: Extraction, as_of: dt.date, config_dir: Path | None = None
) -> CalculationOutcome:
    config_dir = config_dir or CONFIG_DIR
    calc_cfg_path = config_dir / "calculator.yaml"
    outcome = CalculationOutcome(result=None)

    review = [label for name, label in FIELD_LABELS.items() if getattr(ex, name).needs_review]
    if review:
        outcome.warnings.append("Dane wejściowe do sprawdzenia przez prawnika: " + ", ".join(review) + ".")

    outcome.warnings.extend(regime_warnings(ex, calc_cfg_path))
    if ex.waiver_of_claims.value is True:
        outcome.warnings.append(
            "Dokumenty zawierają oświadczenie o zrzeczeniu się roszczeń — kwoty wyliczono, "
            "skuteczność zrzeczenia do oceny prawnika."
        )
    if ex.price_gross.value is None:
        outcome.blocking.append("Brak ceny lokalu.")
    if ex.penalty_basis.value is None:
        outcome.blocking.append("Brak sposobu naliczania kary.")
    if outcome.blocking:
        return outcome

    basis = Basis(ex.penalty_basis.value.value)
    cap = None
    if ex.penalty_cap.value is not None:
        cap = Cap(ex.penalty_cap.value.type, Decimal(ex.penalty_cap.value.value))

    table = None
    if basis is Basis.STATUTORY_INTEREST:
        with calc_cfg_path.open(encoding="utf-8") as fh:
            kind = yaml.safe_load(fh).get("statutory_interest_kind", "late_payment")
        table = load_rate_table(config_dir / "statutory_interest.yaml", kind)
        if not table.periods:
            outcome.blocking.append(
                "Tabela odsetek ustawowych jest pusta — uzupełnij config/statutory_interest.yaml."
            )
            return outcome

    terms = Terms(
        basis=basis,
        price_grosze=round_grosze(Decimal(ex.price_gross.value) * 100),
        rate=Decimal(ex.penalty_rate.value) if ex.penalty_rate.value is not None else None,
        cap=cap,
        interest_table=table,
    )

    if ex.penalty_events.value:
        events = tuple(Event(e.value) for e in ex.penalty_events.value)
    else:
        events = (Event.HANDOVER_DELAY, Event.TRANSFER_DELAY)
        outcome.warnings.append(
            "Dokument nie wskazuje wprost, za jakie opóźnienie należy się kara — "
            "wyliczono dla obu zdarzeń, do oceny prawnika."
        )

    def amendments(field_name: str) -> tuple[Amendment, ...]:
        return tuple(
            Amendment(f.value.date, f.value.annex_no)
            for f in ex.annex_deadlines
            if f.value is not None and f.value.field == field_name
        )

    case = CaseInput(
        terms=terms,
        penalty_events=events,
        as_of=as_of,
        handover_deadline=ex.handover_deadline.value,
        transfer_deadline=ex.transfer_deadline.value,
        handover_amendments=amendments("handover_deadline"),
        transfer_amendments=amendments("transfer_deadline"),
        actual_handover_date=ex.actual_handover_date.value,
        actual_transfer_date=ex.actual_transfer_date.value,
    )
    outcome.result = calculate_case(case, load_calc_config(calc_cfg_path))
    return outcome
