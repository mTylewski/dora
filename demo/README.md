# DORA — demo (Etap A) — Cloudflare Workers

Usługa dla kancelarii dostępna z przeglądarki, bez instalacji. Dokumenty są odczytywane i anonimizowane na komputerze prawnika, a do serwera trafia tylko zatwierdzony tekst bez danych osobowych.

## Jak działa

1. **W przeglądarce prawnika:**
   - odczyt PDF przez pdf.js;
   - OCR skanów przez tesseract.js z polskim modelem, który jest serwowany z naszej domeny (`web/public/ocr`, kopiowany przez `npm run ocr-assets`);
   - anonimizacja (`shared/anonymize.ts`, ta sama co w MVP; test `shared/anonymize.test.ts` porównuje wynik z Pythonem).
2. **Prawnik zatwierdza podgląd tekstu**, który zostanie wysłany. Pliki PDF i mapowanie znaczników na dane osobowe zostają w pamięci karty.
3. **Worker przyjmuje tylko tekst** (`/api/analyze`) i odrzuca go (kod 422 `pii_detected`), jeśli znajdzie PESEL, numer konta, dowód, e-mail, telefon, KW, NIP lub REGON. Uruchamia te same prompty i schematy co MVP: klasyfikacja, potem równolegle ekstrakcja i klauzule. Postęp wysyła strumieniem NDJSON.
4. **W przeglądarce:**
   - weryfikacja cytatów na wysłanym tekście;
   - kalkulator (BigInt, grosze);
   - przywrócenie danych osobowych do wyświetlenia;
   - pismo .docx. Do `/api/justification` idą tylko daty, kwoty i zanonimizowany cytat.

Nic nie jest zapisywane, a po zamknięciu karty dane znikają. Ustawienia kancelarii (nazwa, miejscowość, pełnomocnik, rachunek) przeglądarka pamięta lokalnie (localStorage) dla wygody.

## Uruchomienie lokalne

```bash
cd demo
npm install
npm test                  # parytet kalkulatora i weryfikacji z Pythonem, testy Workera
npm run typecheck
printf 'ANTHROPIC_API_KEY=sk-ant-...
INVITES_REQUIRED=false
' > .dev.vars   # nie commituj
npm run dev:worker        # http://localhost:8787
npm run dev:web           # http://localhost:5173
```

`INVITES_REQUIRED=false` wyłącza zaproszenia lokalnie. Żeby przetestować zaproszenia lokalnie, usuń tę linię,
dodaj `ADMIN_KEY=...` (min. 24 znaki) i twórz linki z `--local`.

## Wdrożenie (Cloudflare Workers)

| Usługa | Adres | Konfiguracja |
|---|---|---|
| strona (statyczna) | https://dora-demo.<subdomena>.workers.dev | `wrangler.web.toml` |
| serwer analizy | https://dora-api.<subdomena>.workers.dev | `wrangler.local.toml` (wzór: `wrangler.toml`) |

```bash
npx wrangler login
cp wrangler.toml wrangler.local.toml   # wpisz id KV i adres strony; plik nie trafia do gita
# sekrety: klucz Anthropic i klucz administratora zaproszeń (ten sam co w zmiennej DORA_ADMIN_KEY)
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put ADMIN_KEY
npm run deploy:worker
VITE_API_URL=https://dora-api.<subdomena>.workers.dev npm run deploy:web
```

Przy zmianie adresu strony wpisz go do `ALLOWED_ORIGINS` w `wrangler.local.toml` i do `.deploy.json`, potem wdroż Workera ponownie.
Wklejając sekret z PowerShella, uważaj na dopisany znak końca linii — pewniej: `wrangler secret bulk plik.json` (plik usuń od razu).

## Zaproszenia (linki do testów)

Serwer analizy przyjmuje tekst tylko z ważnym zaproszeniem. Link `…/#/z/<kod>` zapamiętuje kod w przeglądarce testera;
serwer trzyma tylko skrót SHA-256 kodu, nazwę, limit analiz, datę ważności i licznik (KV `INVITES`).
Analiza zakończona błędem po stronie serwera lub AI nie zużywa limitu; tekst odrzucony za dane osobowe też nie.

Wymaga zmiennej środowiskowej `DORA_ADMIN_KEY` (ustawiona na koncie Windows) i pliku `.deploy.json` z adresami.

```bash
npm run invite -- create --name "Kancelaria Nowak" --limit 10 --days 30   # wypisuje link (tylko raz!)
npm run invite -- list                       # kto, ile zużył, do kiedy, stan
npm run invite -- topup <id> --add 10        # zwiększ limit
npm run invite -- extend <id> --days 14      # przedłuż ważność
npm run invite -- revoke <id>                # wyłącz link od razu
```

## Limity — sprawdź przed pokazem

Nie zakładam limitów z pamięci. Sprawdź aktualne wartości dla swojego planu: https://developers.cloudflare.com/workers/platform/limits/

- **Czas CPU Workera.** Worker dostaje sam tekst (setki KB), ale sprawdza go regułami anonimizacji. Sprawdź limit CPU swojego planu; przy błędach „exceeded CPU” potrzebny będzie plan płatny.
- **Rozmiar żądania.** Worker przyjmuje do 10 dokumentów i 1,5 mln znaków tekstu (`MAX_DOCUMENTS`, `MAX_TOTAL_CHARS`).
- **Czas trwania.** Analiza trwa 1–3 minuty. Worker wysyła co 10 s linię postępu, żeby połączenie nie wygasło.

## Pliki generowane

`shared/generated/*.json` (biblioteka klauzul, konfiguracja) i `../schemas/*.json` są generowane z Pythona:

```bash
python scripts/export_schemas.py
```
