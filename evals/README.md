# Ewaluacja

Zbiór testowy składa się wyłącznie z **publicznych wzorów umów**. Nie umieszczaj tu dokumentów klientów ani prawdziwych danych osobowych.

## Zawartość

- `contracts/`: pliki PDF z publicznymi wzorami. Docelowo 30 wzorów:
  - co najmniej 10 deweloperów,
  - 5 z aneksami terminowymi,
  - 5 słabych skanów,
  - 5 z trudnymi zapisami (limit kary, kara wyłączna, szerokie wyłączenia).
- `expected/<nazwa>.yaml`: ręcznie oznaczone wartości, jeden plik na przypadek (format poniżej).
- `anonymization/cases.yaml`: syntetyczne teksty ze zmyślonymi danymi do bramki „0 przecieków”.
- `runs/`: zapisane wyniki przebiegów, żeby można było ponownie liczyć wyniki bez kosztów API.
- `reports/`: `latest.md` / `latest.json` oraz `baseline.json` do wykrywania regresji.

## Format `expected/<nazwa>.yaml`

```yaml
documents: [wzor_a_umowa.pdf, wzor_a_aneks1.pdf]   # pliki z contracts/
as_of: 2025-01-01
tags: [annex, scan, hard]
fields:                      # pomiń pole, którego nie oceniasz
  developer_name: APM Przykład sp. z o.o.
  agreement_reference: Rep. A nr 1234/2021
  agreement_date: 2021-05-14
  price_gross: 512340.50
  handover_deadline: 2024-03-31
  transfer_deadline: 2024-09-30
  annex_deadlines:
    - {date: 2024-06-30, field: handover_deadline, annex_no: 1}
  penalty_basis: percent_of_price_per_day
  penalty_rate: 0.0002
  penalty_cap: {type: percent, value: 0.05}          # albo null
  penalty_events: [handover_delay, transfer_delay]
  exclusive_penalty_clause: true                     # true / false / null
  waiver_of_claims: null
  actual_handover_date: null                         # wzory zwykle nie mają dat faktycznych
  actual_transfer_date: null
clauses: [penalty-cap-percent, exclusion-broad-force-majeure]   # id z clauses/*.yaml
penalties_grosze: [450000]   # opcjonalnie: ręcznie wyliczone kwoty (bez limitu), w groszach
```

Wzory umów zwykle nie zawierają dat faktycznych. Do testu kalkulatora możesz dołączyć własny, zmyślony protokół odbioru jako PDF.

## Uruchomienie

```bash
python evals/run_evals.py                   # wszystkie przypadki (wywołania API)
python evals/run_evals.py --only wzor_a     # jeden przypadek
python evals/run_evals.py --reuse           # ponowne liczenie wyników z runs/ bez wywołań API
python evals/run_evals.py --anonymization   # sama bramka anonimizacji (bez API)
python evals/run_evals.py --update-baseline # przyjmij bieżący raport jako bazowy
```

Wyniki z `runs/` są ponownie używane tylko wtedy, gdy nie zmieniły się pliki PDF, prompty ani konfiguracja modeli. Każda taka zmiana uruchamia analizę od nowa.

## Progi (CLAUDE.md, sekcja 10)

| Miara | Próg |
|---|---|
| Pola krytyczne (terminy, stawka, limit, cena) | ≥ 95% |
| Pozostałe pola | ≥ 90% |
| Cytaty znalezione lub oznaczone do sprawdzenia | 100% |
| Kalkulator zgodny z ręcznymi wyliczeniami | 100% |
| Wykrycie klauzul | ≥ 90% |
| Fałszywe alarmy klauzul | ≤ 20% |
| Czas analizy jednej sprawy | < 5 min |
| Przecieki danych osobowych | 0 |

Skrypt kończy się kodem 1 w trzech przypadkach:
- próg nie jest spełniony,
- trafność któregoś pola spadła względem `baseline.json`,
- anonimizacja przepuściła dane.

Spadek trafności blokuje wydanie.
