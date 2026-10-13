# CLAUDE.md — Analiza roszczeń wobec deweloperów (projekt Michała Tylewskiego)

Ten plik jest instrukcją dla Claude Code. Czytaj go na początku każdej sesji.
Odpowiadaj po polsku. Kod, nazwy zmiennych i komentarze w kodzie po angielsku.
Autor woli kompletne, działające rozwiązania zamiast szkiców; poprawki daje krótko — wprowadzaj je bez długich wyjaśnień.

---

## 1. Czym jest projekt

Narzędzie B2B dla kancelarii prawnych, które prowadzą sprawy nabywców mieszkań przeciw deweloperom
o kary umowne za opóźnienie (wydanie lokalu, zawarcie umowy przenoszącej własność).

Prawnik wgrywa dokumenty (umowa deweloperska, aneksy, protokół odbioru, akt przeniesienia własności),
a system w kilka minut zwraca:

1. kartę sprawy: terminy, cena, stawka kary, limity, wyłączenia, faktyczne daty — **każde pole z dosłownym cytatem i numerem strony**,
2. wyliczenie kary i oś czasu,
3. flagi prawdopodobnie abuzywnych klauzul z uzasadnieniem,
4. projekt wezwania do zapłaty w .docx na szablonie kancelarii.

System przygotowuje projekt. Decyzję podejmuje i pismo podpisuje prawnik. Nigdy nie formułuj w UI ani w pismach
treści sugerujących, że to porada prawna systemu.

Klientem płacącym jest kancelaria (licencja + wdrożenie). Nie budujemy produktu dla konsumentów.

---

## 2. Dwa etapy — nie mieszaj ich

### Etap A: usługa w przeglądarce (Cloudflare) — demo i pilotaż dla kancelarii
- Cel: kancelaria dostaje link i korzysta bez instalacji. Decyzja autora (październik 2026): anonimizacja w przeglądarce.
- Cloudflare Pages (frontend) + Cloudflare Worker w TypeScript (backend).
- **PDF nigdy nie opuszcza komputera prawnika**: odczyt (pdf.js), OCR skanów (tesseract.js, model `pol` serwowany z naszej domeny)
  i anonymizacja (port `pipeline/anonymize.py` w `demo/shared/anonymize.ts`, zgodność pilnowana testem) działają w przeglądarce.
- Prawnik zatwierdza podgląd zanonimizowanego tekstu; Worker przyjmuje **wyłącznie tekst** i odrzuca go, jeśli wykryje identyfikatory
  (PESEL, konto, dowód itd.). Kroki jak w MVP: klasyfikacja → ekstrakcja + klauzule. Mapowanie znaczników zostaje w pamięci przeglądarki.
- Klucz API wyłącznie jako sekret Workera: `wrangler secret put ANTHROPIC_API_KEY`. Nigdy w kodzie frontendu.
- Kalkulator w TypeScript w przeglądarce; .docx generowany w przeglądarce (biblioteka `docx`).
- Brak bazy danych i zapisu plików — wyniki znikają po zamknięciu karty.
- Anonimizacja nie jest stuprocentowa: przy prawdziwych dokumentach umowa z kancelarią (powierzenie) pozostaje wskazana — do oceny prawnika.
- Opcjonalnie Cloudflare Access (logowanie mailem) przed usługą.
- Limity planu Cloudflare sprawdź w aktualnej dokumentacji, nie zakładaj z pamięci.

### Etap B: MVP produkcyjne — wdrażane na serwerze kancelarii
- Wszystko działa na serwerze kancelarii (VPS w UE na **koncie kancelarii**). Konto Claude API też należy do kancelarii.
- Do Claude API wychodzi tylko zanonimizowany tekst. Aktualizacje serwer pobiera sam (pull), dostawca nie loguje się na serwer.
- Szczegóły w sekcjach 4–9.

Domyślnie pracujemy nad tym etapem, o który prosi autor. Jeśli nie jest jasne — zapytaj jednym zdaniem.

---

## 3. Zasady nienaruszalne (dotyczą obu etapów)

1. **LLM nigdy nie liczy pieniędzy ani dni.** Wszystkie obliczenia robi deterministyczny kod z testami.
2. **Każde wyciągnięte pole ma dosłowny cytat i numer strony.** Kod weryfikuje, że cytat występuje w tekście dokumentu
   (po normalizacji białych znaków). Cytat nieznaleziony → pole oznaczone `needs_review: true`.
3. **Brak wartości w dokumencie = `null`, nigdy domysł.** Prompt musi to wymuszać.
4. **Model nie ma narzędzi ani dostępu do sieci.** Pipeline to stały ciąg kroków, nie autonomiczny agent.
   Jeśli używasz tool use, to wyłącznie jako sposobu wymuszenia schematu JSON (narzędzie nigdy niczego nie wykonuje).
5. **Odpowiedź modelu walidowana schematem** (Pydantic / zod). Niezgodna → jedna ponowna próba, potem błąd do UI.
6. **Treść dokumentów nigdy w logach.** Logi techniczne: id sprawy, krok, czas, tokeny, kod błędu.
7. **Prawdziwe dane osobowe nigdy w repozytorium, testach ani fixture'ach.** Zbiór testowy = publiczne wzory umów.
8. Nie wymyślaj przepisów, sygnatur ani stawek. Wszystko prawne trzymaj w plikach konfiguracyjnych (`clauses/`, `config/`)
   z polem `source` i oznaczeniem `verified: false`, dopóki autor lub prawnik nie potwierdzi.

---

## 4. Pipeline (Etap B)

| Krok | Wykonawca | Wyjście |
|---|---|---|
| 0. Tekst z PDF | `pdfplumber`; jeśli brak warstwy tekstowej → OCR lokalny (PaddleOCR lub Tesseract `pol`) | tekst + numer strony + pozycje słów |
| 1. Anonimizacja | kod lokalny: reguły + NER | tekst ze znacznikami `[NABYWCA_1]`, mapowanie szyfrowane lokalnie |
| 2. Klasyfikacja dokumentów | `claude-haiku-4-5-20251001` | typ: `development_agreement`, `annex`, `handover_protocol`, `transfer_deed`, `other` |
| 3. Ekstrakcja | `claude-sonnet-5-5` | JSON wg `schemas/extraction.json` |
| 4. Weryfikacja cytatów | kod | `needs_review` dla nieznalezionych cytatów |
| 5. Kalkulator | kod, bez LLM | dni opóźnienia, kwota, limit, odsetki |
| 6. Ocena klauzul | `claude-opus-5-5` + biblioteka wzorców w prompcie systemowym (prompt caching) | flagi z uzasadnieniem i cytatem |
| 7. Pismo | szablon `.docx` + `claude-sonnet-5-5` tylko do akapitu uzasadnienia | projekt wezwania, dane osobowe przywrócone lokalnie |

W etapie A kroki 0–1 (odczyt, OCR, anonimizacja) działają w przeglądarce; Worker wykonuje kroki 2, 3 i 6 na zatwierdzonym tekście.

Model strings trzymaj w konfiguracji (`config/models.yaml` / zmienne środowiskowe), nie w kodzie.
Przed użyciem funkcji API (structured outputs, prompt caching, PDF input) sprawdź aktualną dokumentację:
https://platform.claude.com/docs — nie zakładaj z pamięci.

### Anonimizacja — szczegóły
- Reguły (regex + walidacja sum kontrolnych tam, gdzie istnieją): PESEL, NIP, REGON, numer dowodu, numer księgi wieczystej,
  IBAN / numer konta, kod pocztowy, e-mail, telefon.
- NER dla imion, nazwisk, adresów: spaCy (polski model — **sprawdź licencję modelu pod kątem użycia komercyjnego**)
  lub mały lokalny model. Nazwisko znalezione w komparycji stron podmieniaj w całym dokumencie.
- Do API wysyłamy **tekst**, nigdy obraz skanu (obraz zawiera dane osobowe).
- UI pokazuje prawnikowi, co zanonimizowano, przed wysłaniem do API (tryb zatwierdzania włączany w konfiguracji).
- Brama jakości: 0 przecieków danych osobowych na zbiorze testowym.

---

## 5. Schemat ekstrakcji (`schemas/extraction.json`)

Każde pole ma strukturę `Field`:

```json
{
  "value": "...",          // typ zależny od pola; null gdy brak w dokumencie
  "quote": "...",          // dosłowny fragment dokumentu, null gdy value null
  "page": 3,               // numer strony w dokumencie źródłowym
  "document_id": "doc_1",
  "confidence": "high|medium|low",
  "needs_review": false     // ustawia kod, nie model
}
```

Pola (minimum):

| Pole | Typ value | Uwagi |
|---|---|---|
| `developer_name` | tekst | nazwa dewelopera z umowy (do pisma) |
| `agreement_reference` | tekst | numer aktu notarialnego umowy, np. „Rep. A nr 1234/2021” (do pisma) |
| `agreement_date` | data ISO | data zawarcia umowy deweloperskiej; umowy sprzed nowej ustawy (granica w `config/calculator.yaml`) są oznaczane do sprawdzenia przepisów przejściowych |
| `price_gross` | liczba (PLN) | cena lokalu z umowy |
| `handover_deadline` | data ISO | termin wydania lokalu |
| `transfer_deadline` | data ISO | termin zawarcia umowy przenoszącej własność |
| `annex_deadlines[]` | lista {date, field, annex_no} | terminy zmienione aneksami |
| `penalty_basis` | enum: `percent_of_price_per_day`, `fixed_per_day`, `statutory_interest`, `other` | |
| `penalty_rate` | liczba | np. 0.0002 dla 0,02% dziennie |
| `penalty_cap` | {type: percent/amount, value} lub null | limit kary |
| `penalty_events[]` | lista enum: `handover_delay`, `transfer_delay` | za co kara przysługuje |
| `liability_exclusions[]` | lista cytatów | siła wyższa, decyzje urzędów, przyłącza itd. |
| `exclusive_penalty_clause` | bool | brak prawa do odszkodowania ponad karę |
| `waiver_of_claims` | bool | zrzeczenie się roszczeń (zwykle w akcie przeniesienia) |
| `actual_handover_date` | data ISO | z protokołu odbioru |
| `actual_transfer_date` | data ISO | z aktu przeniesienia własności |

Rozszerzaj schemat tylko po uzgodnieniu z autorem; każda zmiana schematu = aktualizacja zbioru testowego.

---

## 6. Kalkulator (`calculator/`)

- Czysty kod (Python w MVP, TypeScript w demo), 100% pokrycia testami, przykłady liczone ręcznie w testach.
- Dni opóźnienia: liczone od dnia następującego po terminie do faktycznej daty. **Sposób liczenia (włącznie/wyłącznie)
  jest parametrem konfiguracyjnym do potwierdzenia z prawnikiem** — nie zakładaj.
- Termin efektywny = najpóźniejszy termin z umowy po aneksach (aneks ma pierwszeństwo).
- Kwota = cena × stawka × dni (dla `percent_of_price_per_day`) / stawka × dni (dla `fixed_per_day`).
  Dla `statutory_interest` — stawki odsetek ustawowych z tabeli `config/statutory_interest.yaml`
  (okresy obowiązywania + źródło), nigdy wartość wpisana w kod.
- Limit: licz kwotę bez limitu i z limitem; pokaż obie i oznacz limit jako potencjalnie abuzywny do oceny prawnika.
- Kwoty jako `Decimal` / liczby całkowite w groszach. Nigdy float dla pieniędzy.
- Wynik zawiera ścieżkę obliczeń (dane wejściowe, wzór, wynik) do pokazania w UI.

---

## 7. Biblioteka klauzul (`clauses/*.yaml`)

```yaml
- id: penalty-cap-5-percent
  title: Limit kary umownej (np. 5% ceny)
  pattern_description: Kara za opóźnienie ograniczona do stałego procentu ceny niezależnie od długości opóźnienia.
  why_risky: ...
  source: "decyzja UOKiK / orzeczenie — uzupełnić sygnaturę"
  verified: false
```

- Na start 30–50 wzorców. Treść i źródła uzupełnia autor (docelowo z prawnikiem). Nie generuj sygnatur ani dat orzeczeń.
- Biblioteka trafia do promptu systemowego kroku 6 z prompt caching.
- Model zwraca dla każdej flagi: `clause_id`, `quote`, `page`, `reasoning` (2–3 zdania), `confidence`.

---

## 8. Bezpieczeństwo (Etap B)

- Serwer i konto API należą do kancelarii. Dostęp instalacyjny jest odbierany po wdrożeniu.
- Firewall wychodzący (nftables): dozwolony ruch tylko do API modelu i rejestru obrazów kontenerów.
- Szyfrowany wolumen na pliki i bazę; TLS dla UI; logowanie z 2FA; role `lawyer`, `admin`.
- Dziennik dostępu do każdej sprawy. Automatyczne usuwanie spraw po okresie z konfiguracji.
- Aktualizacje: podpisane obrazy kontenerów, serwer kancelarii sam je pobiera.
- Dokumentacja dla kancelarii w `docs/`: schemat przepływu danych, instrukcja, wzór umowy powierzenia (treść prawną uzupełnia prawnik).
- Kancelaria może wystąpić do Anthropic o zero data retention dla swojego konta — opisz to w dokumentacji, nie obiecuj w imieniu Anthropic.

---

## 9. Stack i struktura repozytorium

MVP: Python 3.12, FastAPI, Redis + RQ, PostgreSQL 16, pdfplumber, PaddleOCR / Tesseract, spaCy, python-docx,
oficjalne SDK `anthropic`, Docker Compose, Ansible, nftables.
Demo: TypeScript, Cloudflare Workers + Pages, `wrangler`, biblioteka `docx`.

```
claims-app/
  CLAUDE.md
  demo/            # Etap A: worker/ (TS), web/ (Pages), wrangler.toml
  app/             # FastAPI: sprawy, użytkownicy, API
  pipeline/        # pdf_text, ocr, anonymize, classify, extract, verify_quotes, clauses, letter
  calculator/      # deterministyczne wyliczenia + testy
  clauses/         # biblioteka wzorców (YAML)
  schemas/         # extraction.json, clauses_output.json
  config/          # models.yaml, statutory_interest.yaml, settings
  templates/       # szablony pism .docx
  web/             # frontend MVP
  evals/           # contracts/ (publiczne wzory), expected/ (oczekiwane wartości), run_evals.py
  deploy/          # docker-compose.yml, ansible/, nftables.conf
  docs/            # dla kancelarii: przepływ danych, instrukcja, wzory umów
```

---

## 10. Jakość i zbiór testowy (`evals/`)

- 30 publicznych wzorów umów: ≥10 deweloperów, 5 z aneksami terminowymi, 5 słabych skanów, 5 z trudnymi zapisami
  (limit kary, kara wyłączna, szerokie wyłączenia).
- `expected/` = ręcznie oznaczone wartości pól i flagi. Skrypt `run_evals.py` liczy trafność per pole i raportuje regresje.
- Progi: pola krytyczne (terminy, stawka, limit, cena) ≥ 95%; pozostałe ≥ 90%; cytaty 100% znalezione lub oznaczone;
  kalkulator 100%; klauzule wykrycie ≥ 90%, fałszywe alarmy ≤ 20%; czas analizy < 5 min; anonimizacja 0 przecieków.
- Uruchamiaj evale po każdej zmianie promptu, schematu lub modelu. Spadek trafności blokuje wydanie.

---

## 11. Plan i bramy

1. Tydz. 1–2: zbiór testowy, schemat, ekstrakcja z cytatami → **brama: ≥ 90% trafności pól**.
2. Tydz. 3–4: kalkulator, weryfikacja cytatów, biblioteka klauzul → **brama: kalkulator 100% zgodny z ręcznymi wyliczeniami**.
3. Tydz. 5–6: aplikacja dla prawnika (sprawy, przegląd z podglądem PDF, poprawki, .docx).
4. Tydz. 7–8: OCR, anonimizacja, firewall, szyfrowanie, Ansible, aktualizacje → **brama: instalacja < 1 h, 0 przecieków PII**.
5. Tydz. 9–10: demo, strona z wynikami, dokumenty, pilotaż z kancelarią.

Demo na Cloudflare (Etap A) można zbudować wcześniej, równolegle z tygodniami 1–2, bo korzysta z tego samego promptu i schematu.

---

## 12. Jak pracować z autorem

- Przed większą zmianą (nowy moduł, zmiana schematu, zmiana architektury) — krótki plan w 3–5 punktach, potem kod.
- Dostarczaj kompletne pliki, gotowe do uruchomienia, z testami i instrukcją uruchomienia w README.
- Gdy czegoś nie wiesz (przepisy, limity usług, ceny, możliwości API) — powiedz to i wskaż, gdzie sprawdzić. Nie zgaduj.
- Nie rozszerzaj zakresu poza MVP (wady techniczne, metraż, pozwy, integracje, wersja multi-tenant w chmurze) bez prośby autora.

## 13. Otwarte kwestie (do rozstrzygnięcia przez autora / prawnika)

- Sposób liczenia dni opóźnienia (włącznie / wyłącznie dnia terminu).
- Treść i źródła wzorców klauzul (`verified: true` dopiero po potwierdzeniu).
- Licencja polskiego modelu spaCy do użytku komercyjnego.
