# Analiza roszczeń wobec deweloperów

Narzędzie dla kancelarii prowadzących sprawy nabywców mieszkań o kary umowne za opóźnienie dewelopera. Z dokumentów sprawy przygotowuje projekt:

1. **Karta sprawy:** terminy, cena, stawka i limit kary, wyłączenia, faktyczne daty. Każde pole ma dosłowny cytat i numer strony, a kod sprawdza, że cytat występuje w dokumencie.
2. **Wyliczenie kary i oś czasu.** Liczy deterministyczny kalkulator; model językowy nie liczy pieniędzy ani dni.
3. **Flagi klauzul** pasujących do wzorców z biblioteki kancelarii.
4. **Projekt wezwania do zapłaty** w formacie .docx.

Decyzję podejmuje i pismo podpisuje prawnik. Instrukcja dla Claude Code jest w [CLAUDE.md](../CLAUDE.md).

## Struktura

| Katalog | Zawartość |
|---|---|
| `calculator/` | kalkulator (Python, `Decimal`/grosze, 100% pokrycia testami) |
| `pipeline/` | kroki analizy: PDF → OCR → anonimizacja → klasyfikacja → ekstrakcja → weryfikacja cytatów → kalkulator → klauzule → pismo |
| `app/` | aplikacja web dla prawnika (FastAPI): logowanie z 2FA, sprawy, zatwierdzanie anonimizacji, przegląd, poprawki, pismo, dziennik dostępu |
| `web/` | szablony HTML i CSS aplikacji |
| `prompts/` | prompty systemowe (wspólne dla MVP i demo) |
| `schemas/` | schematy JSON generowane z modeli Pydantic |
| `config/` | modele, kalkulator, odsetki ustawowe, pismo |
| `clauses/` | biblioteka wzorców klauzul (YAML, `verified: false` do potwierdzenia) |
| `templates/` | szablon pisma .docx |
| `evals/` | zbiór testowy, scoring, bramka anonimizacji |
| `demo/` | Etap A: Cloudflare Worker + strona demo (TypeScript) |
| `deploy/` | Docker Compose, Ansible, nftables, aktualizacje z podpisem |
| `docs/` | dokumentacja dla kancelarii |

## Uruchomienie lokalne (MVP)

Wymagania: Python 3.12+. Do OCR: Tesseract z językiem `pol` (opcjonalnie).

```bash
python -m venv .venv
.venv/Scripts/activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev,ocr]"
pytest --cov                      # testy; kalkulator wymaga 100% pokrycia
```

Analiza z linii poleceń, tylko na publicznych wzorach umów:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/analyze.py umowa.pdf aneks.pdf --out wynik.json --letter wezwanie.docx
python scripts/analyze.py umowa.pdf --show-anonymized    # podgląd anonimizacji, nic nie jest wysyłane
```

Aplikacja web lokalnie (SQLite, zadania w tle uruchamiane w procesie):

```bash
export CLAIMS_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export CLAIMS_MAPPING_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export CLAIMS_SECURE_COOKIES=false CLAIMS_DATA_DIR=./data CLAIMS_DATABASE_URL=sqlite:///./data/claims.db
mkdir -p data
python -m app.cli create-user admin@example.com --role admin   # pokaże adres otpauth:// do aplikacji 2FA
uvicorn app.main:build --factory --reload
```

Produkcja: [docs/instalacja.md](instalacja.md).

## Pliki generowane

Po zmianie modeli Pydantic, biblioteki klauzul lub konfiguracji uruchom:

```bash
python scripts/export_schemas.py        # schemas/*.json, demo/shared/generated/*.json
python scripts/make_letter_template.py  # templates/wezwanie_do_zaplaty.docx (szablon domyślny)
```

Test `test_committed_schemas_are_up_to_date` nie przejdzie, jeśli pliki są nieaktualne.

## Ewaluacja

Zobacz [evals/README.md](../evals/README.md). Evale uruchamiaj po każdej zmianie promptu, schematu lub modelu.

## Do rozstrzygnięcia (autor / prawnik)

Wartości w konfiguracji oznaczone `verified: false` to założenia robocze:

- `config/calculator.yaml`:
  - czy dzień faktycznego wydania wlicza się do opóźnienia (obecnie: tak),
  - rok do odsetek: 365 dni,
  - którą tabelę odsetek stosować.
- `config/statutory_interest.yaml`: tabele stawek są puste. Trzeba je uzupełnić z obwieszczeń wraz ze źródłem.
- `config/letter.yaml`: podstawa prawna w piśmie.
- `clauses/*.yaml`: źródła wzorców (sygnatury, decyzje).
- Przy kilku aneksach obowiązuje termin z aneksu o najwyższym numerze, a przy aneksach bez numerów termin z ostatniego w kolejności dokumentów.
- Gdy umowa nie wskazuje, za jakie opóźnienie należy się kara, system liczy oba warianty z ostrzeżeniem.
- Pozostałe kwestie: CLAUDE.md, sekcja 13.
