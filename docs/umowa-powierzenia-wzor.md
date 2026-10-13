# Wzór umowy powierzenia przetwarzania danych osobowych — szkielet

> **Projekt struktury, nie treść prawna.** Treść postanowień uzupełnia prawnik.
> Najpierw trzeba rozstrzygnąć, czy dostawca systemu w ogóle jest podmiotem przetwarzającym, skoro system działa na serwerze kancelarii, a dostawca nie ma do niego dostępu po wdrożeniu (otwarta kwestia w CLAUDE.md, sekcja 13). Od tego zależy, czy ta umowa jest potrzebna i w jakim zakresie, np. tylko na czas instalacji i wsparcia.

## Strony
- Administrator: [kancelaria]
- Podmiot przetwarzający: [dostawca systemu] — [DO USTALENIA, czy i w jakim zakresie]

## 1. Przedmiot i czas trwania
[DO UZUPEŁNIENIA: np. instalacja systemu na serwerze administratora, wsparcie techniczne na zlecenie]

## 2. Charakter i cel przetwarzania
[DO UZUPEŁNIENIA]

## 3. Rodzaje danych i kategorie osób
[DO UZUPEŁNIENIA: dane nabywców lokali i innych osób wymienionych w dokumentach; użytkownicy systemu]

## 4. Obowiązki podmiotu przetwarzającego
[DO UZUPEŁNIENIA]

## 5. Środki techniczne i organizacyjne

Fakty techniczne, które prawnik może wykorzystać (szczegóły w `docs/przeplyw-danych.md`):

- **Infrastruktura:** system działa na serwerze administratora, na jego koncie u dostawcy VPS w UE.
- **Szyfrowanie:**
  - wolumen danych szyfrowany LUKS,
  - dane spraw w bazie dodatkowo szyfrowane kluczem aplikacji,
  - połączenia przez TLS.
- **Dostęp do systemu:**
  - logowanie z hasłem (argon2) i drugim składnikiem (TOTP),
  - role prawnik / administrator,
  - dziennik dostępu do każdej sprawy.
- **Model językowy:** do usługi modelu trafia wyłącznie tekst po anonimizacji, zatwierdzony przez prawnika. Konto usługi należy do administratora.
- **Sieć:** zapora ruchu wychodzącego ogranicza połączenia do API modelu, rejestru obrazów i aktualizacji systemu.
- **Retencja:** automatyczne usuwanie spraw po okresie ustalonym przez administratora.
- **Aktualizacje i dostęp dostawcy:**
  - aktualizacje są pobierane przez serwer i weryfikowane podpisem,
  - dostawca nie ma dostępu do serwera po wdrożeniu.

## 6. Dalsze powierzenie

Anthropic (usługa Claude API) jest dostawcą administratora na podstawie umowy zawartej bezpośrednio przez administratora, a nie podwykonawcą dostawcy systemu.

[DO WERYFIKACJI przez prawnika]

## 7. Prawa audytu, naruszenia, zakończenie umowy
[DO UZUPEŁNIENIA]
