"""Regenerate files derived from the Python sources of truth.

  schemas/*.json                 - JSON schemas generated from the Pydantic models
  demo/shared/generated/*.json   - clause library and configuration for the Cloudflare demo

Usage: python scripts/export_schemas.py   (a test fails when these files are stale)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.clauses import clauses_output_json_schema, load_library, render_library  # noqa: E402
from pipeline.classify import Classification  # noqa: E402
from pipeline.letter import Justification  # noqa: E402
from pipeline.schema import extraction_json_schema, model_output_json_schema, strict_schema  # noqa: E402


def _yaml(name: str):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def clause_library() -> dict:
    patterns = load_library()
    return {
        "rendered": render_library(patterns),
        "patterns": [
            {"id": p.id, "title": p.title, "source": p.source, "verified": p.verified}
            for p in sorted(patterns, key=lambda p: p.id)
        ],
    }


def demo_config() -> dict:
    models = _yaml("models.yaml")["steps"]
    calc = _yaml("calculator.yaml")
    letter = _yaml("letter.yaml")
    rates = _yaml("statutory_interest.yaml")
    return {
        "models": {k: {kk: vv for kk, vv in v.items()} for k, v in models.items()},
        "calculator": {
            "include_actual_date": calc["day_count"]["include_actual_date"],
            "verified": calc["day_count"].get("verified", False),
            "interest_year_days": calc.get("interest_year_days", 365),
            "statutory_interest_kind": calc.get("statutory_interest_kind", "late_payment"),
            "new_act_from": str((calc.get("development_act") or {}).get("new_act_from") or ""),
            "new_act_verified": bool((calc.get("development_act") or {}).get("verified", False)),
        },
        "statutory_interest": {
            kind: [{**p, "from": str(p["from"]), "to": str(p["to"]) if p.get("to") else None}
                   for p in (data.get("periods") or [])]
            for kind, data in rates["kinds"].items()
        },
        "letter": {"payment_deadline_days": letter.get("payment_deadline_days", 14),
                   "legal_basis": (letter.get("legal_basis") or {}).get("text") or ""},
    }


def anonymization_parity() -> dict:
    """Python results on synthetic texts; the TypeScript port must reproduce them exactly."""
    from pipeline.anonymize import anonymize_pages
    from pipeline.tests.test_anonymize import AGREEMENT, DEED

    cases = yaml.safe_load((ROOT / "evals" / "anonymization" / "cases.yaml").read_text(encoding="utf-8"))
    inputs = [{"name": c["name"], "documents": {"d": [c["text"]]}, "secrets": c["secrets"]} for c in cases]
    inputs += [
        {"name": "agreement_and_deed", "documents": {"doc_1": [AGREEMENT], "doc_2": [DEED]}, "secrets": []},
        {"name": "family", "documents": {"d": [
            "Nabywca: Natalia Testowa" + chr(10) + "Nabywca: Paweł Testowy" + chr(10)
            + "Pawłowi Testowemu i Natalii Testowej wydano lokal."]}, "secrets": []},
        {"name": "terms", "documents": {"d": [
            "Nabywca: Karol Stroński" + chr(10) + "Nabywca zapłaci Deweloperowi Cenę Całkowitą."
            + " Zawarcie Umowy Przenoszącej nastąpi po Wydaniu Lokalu Mieszkalnego."]},
         "secrets": ["Karol", "Stroński"]},
        {"name": "role_after_entry", "documents": {"d": [
            "Stawili się: 1. Jan Zmyślony, PESEL 85071512348, działający w imieniu Budowa Test sp. z o.o., zwanej dalej"
            " „Deweloperem”, 2. Pani Katarzyna Fikcyjna, córka Adama, oraz Pan Bartłomiej Fikcyjny, syn Jana,"
            " zwani dalej łącznie „Nabywcą”."]}, "secrets": ["Zmyślony", "Fikcyjna", "Fikcyjny"]},
        {"name": "two_first_names", "documents": {"d": [
            "przed notariuszem Tadeuszem Romualdem Testowym, stawili się:" + chr(10)
            + "1/ Adam Michał Zmyślony, używający imienia Adam, syn Romana i Teresy, PESEL 85071512348, działający za"
            + " spółkę Budowa Test sp. z o.o." + chr(10)
            + "2/ Natalia Zofia Fikcyjna, używająca imienia Natalia, córka Pawła i Elżbiety. Spółka zwana będzie w dalszej"
            + " treści niniejszego aktu również jako „Spółka” lub „Deweloper”, Adam Zmyślony również jako „Przedstawiciel"
            + " Dewelopera”, natomiast Natalia Fikcyjna zwana będzie również jako „Nabywca”. Według aktu notariusza w"
            + " Zakopanem Łukasza Próbnego."]},
         "secrets": ["Zmyślony", "Michał", "Fikcyjna", "Zofia", "Testowym", "Romualdem", "Romana", "Elżbiety", "Próbnego"]},
        {"name": "ocr_email", "documents": {"d": [
            "drogą mailową na adres: „anna. testowaQexample.com” lub jan.probny © example.org, albo kontakt(at)test.pl."
            " Pozostały tekst: kwota 1.080.000,00 zł, wersja 2.1, Q1 2026."]},
         "secrets": ["testowaQexample", "jan.probny", "kontakt(at)test.pl"]},
    ]
    out = []
    for case in inputs:
        pages, anon = anonymize_pages(case["documents"])
        out.append({
            "name": case["name"], "documents": case["documents"], "secrets": case["secrets"],
            "expected": pages, "mapping": anon.mapping,
            "persons": [{"token": t, **p} for t, p in anon.persons.items()],
        })
    return {"cases": out}


def letter_parity() -> dict:
    """Python letter texts for fixed inputs; the TypeScript port must produce identical values."""
    import datetime as dt

    from pipeline.letter import PLACEHOLDERS, LetterParties, letter_values

    full = LetterParties(
        clients=(("Jan Testowy", "ul. Próbna 1, 00-001 Warszawa"), ("Anna Testowa", "")),
        client_name="Jan Testowy i Anna Testowa", developer_name="APM Test sp. z o.o.", developer_address="ul. Budowlana 2",
        agreement_date="10.01.2023", agreement_deed="Rep. A nr 100/2023", bank_account="11 1111 1111",
        case_number="KAN/2026/001", lawyer_name="Anna Prawnicza", lawyer_title="radca prawny", lawyer_registry="WA-1",
        firm_name="Kancelaria Testowa", firm_address="ul. Testowa 1", city="Warszawa", payment_deadline_days=7,
        legal_basis="",
    )
    empty = LetterParties()
    config = {"firm": {}, "payment_deadline_days": 14, "legal_basis": {"text": ""}}
    day = dt.date(2026, 10, 6)
    return {
        "placeholders": PLACEHOLDERS,
        "cases": [
            {"name": "full", "parties": "full", "values": letter_values(full, 680400, "Akapit.", day, config)},
            {"name": "empty", "parties": "empty", "values": letter_values(empty, 0, "", day, config)},
        ],
    }


TARGETS = {
    "schemas/extraction.json": extraction_json_schema,
    "schemas/extraction_model_output.json": model_output_json_schema,
    "schemas/clauses_output.json": clauses_output_json_schema,
    "schemas/justification_output.json": lambda: strict_schema(Justification.model_json_schema()),
    "schemas/classification_output.json": lambda: strict_schema(Classification.model_json_schema()),
    "demo/shared/generated/clause_library.json": clause_library,
    "demo/shared/generated/config.json": demo_config,
    "demo/shared/generated/anonymization_parity.json": anonymization_parity,
    "demo/shared/generated/letter_parity.json": letter_parity,
}


def render(fn) -> str:
    return json.dumps(fn(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    for name, fn in TARGETS.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(fn), encoding="utf-8", newline="\n")
        print(f"written {name}")


if __name__ == "__main__":
    main()
