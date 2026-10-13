# Instrukcja dla prawnika

System przygotowuje projekt analizy sprawy i projekt wezwania do zapłaty. Każdy wynik wymaga sprawdzenia z dokumentem źródłowym. Decyzję o roszczeniu podejmuje i pismo podpisuje prawnik.

## 1. Logowanie

Logujesz się adresem e-mail, hasłem i 6-cyfrowym kodem z aplikacji uwierzytelniającej. Kod do aplikacji (QR) przekazuje administrator kancelarii przy zakładaniu konta. Po 5 błędnych próbach logowanie jest blokowane na 15 minut.

## 2. Nowa sprawa

1. Kliknij **Nowa sprawa**.
2. Wpisz nazwę sprawy, np. sygnaturę wewnętrzną. Nie wpisuj w nazwie danych osobowych.
3. Ustaw datę wyliczenia. Jeśli opóźnienie trwa, kara jest liczona do tego dnia.
4. Wgraj pliki PDF: umowę deweloperską, aneksy, protokół odbioru, akt przeniesienia własności. Skany są odczytywane lokalnie przez OCR.

## 3. Zatwierdzenie anonimizacji

Po odczycie dokumentów zobaczysz:
- listę danych, które zostaną zastąpione znacznikami (np. `[OSOBA_1]`, `[PESEL_1]`),
- podgląd tekstu, który trafi do modelu.

Przejrzyj podgląd. Jeśli widzisz w nim dane osobowe, **nie zatwierdzaj** i zgłoś to administratorowi. Po zatwierdzeniu analiza trwa zwykle kilka minut, a strona odświeża się sama.

## 4. Karta sprawy

Każde pole ma:
- wartość,
- dosłowny cytat z dokumentu. Kliknięcie cytatu otwiera dokument po prawej na właściwej stronie.

Pola oznaczone **do sprawdzenia** wymagają szczególnej uwagi. System oznacza tak pole, gdy:
- nie znalazł cytatu w tekście dokumentu,
- cytat jest na innej stronie niż wskazana,
- pewność jest niska,
- wartości nie da się ustalić z dokumentu (np. termin określony względnie).

Poprawianie pól:
- **Potwierdź** zapisuje wartość z pola: bez zmian oznacza pole jako „potwierdzone”, po zmianie jako „wpisane przez prawnika”. Formaty: daty `DD.MM.RRRR`, kwoty np. `450000,00`, limit np. `5%` lub `20000`, puste pole oznacza brak.

Każda poprawka trafia do dziennika dostępu, a wyliczenie przelicza się od razu.

## 5. Wyliczenie kary

Wyliczenie pokazuje:
- termin efektywny (z umowy lub z aneksu),
- liczbę dni opóźnienia,
- wzór i kwotę.

Jeśli umowa ogranicza karę, widzisz obie kwoty: **bez limitu** i **z limitem**. Limit jest oznaczony jako klauzula do oceny.

Sposób liczenia dni (czy dzień faktycznego wydania wlicza się do opóźnienia) jest ustawiony w konfiguracji. Dopóki nie zostanie potwierdzony, system wyświetla ostrzeżenie.

## 6. Klauzule do oceny

System wskazuje fragmenty umowy, które pasują do wzorców z biblioteki klauzul kancelarii (np. limit kary, szeroka definicja siły wyższej, zrzeczenie się roszczeń). Każda flaga ma cytat i krótkie uzasadnienie.

Flaga nie przesądza, że klauzula jest abuzywna. To wskazówka do oceny prawnika.

## 7. Pismo (kreator)

Kliknij **Pismo** w sprawie. Kreator ma pięć części, a dane są podpowiedziane z dokumentów i ustawień kancelarii:

1. **Rodzaj pisma**: wybór spośród szablonów kancelarii (np. wezwanie przedsądowe, ostateczne wezwanie).
2. **Mocodawcy**: osoby rozpoznane jako nabywcy w komparycji, z adresami. Dane osobowe są przywracane lokalnie i nie trafiają do modelu. Zaznacz właściwe osoby albo dopisz brakujące.
3. **Deweloper i umowa**: nazwa dewelopera, data i numer aktu notarialnego umowy, odczytane z dokumentu.
4. **Kancelaria**: sygnatura, prawnik podpisujący, rachunek do zapłaty, termin zapłaty.
5. **Kwota żądania**: z limitem umownym albo bez.

**Przygotuj projekt pisma** przenosi do edycji treści:
- Każdy tekst można poprawić. Tabela z wyliczeniem pochodzi z kalkulatora i nie podlega edycji.
- Jeśli szablon ma pole uzasadnienia, model przygotowuje jego projekt na podstawie dat i kwot, bez danych osobowych. Liczby spoza danych sprawy są zgłaszane.
- **Zapisz i pobierz .docx** tworzy plik na wybranym szablonie.
- Jeśli po przygotowaniu projektu zmienisz kartę sprawy i zmieni się wyliczenie, ekran edycji pokaże ostrzeżenie.

Pismo ma nagłówek **PROJEKT** i pola `[UZUPEŁNIJ: …]`. Uzupełnij je, a przed podpisaniem usuń nagłówek.

## 8. Usuwanie

Sprawę można usunąć ręcznie: zaznacz „potwierdzam” i kliknij **Usuń sprawę**. Sprawy są też usuwane automatycznie po okresie retencji ustawionym przez kancelarię.
