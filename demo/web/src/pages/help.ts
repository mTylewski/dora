// Onboarding: short overview for the first-run screen, the "getting started" checklist on the cases page
// and the full user guide (menu "Instrukcja").
import { getFirm, getProfile, listCases, listLawyers, listTemplates, v } from "../store";
import { button, h, type Child } from "../ui";

const PROMISES: [string, string][] = [
  ["🔒", "Dokumenty zostają na Twoim komputerze"],
  ["📌", "Każda dana z cytatem i numerem strony"],
  ["✍️", "Decyzja i podpis zawsze należą do Ciebie"],
];

const pills = () => h("div", { class: "pills" }, ...PROMISES.map(([icon, text]) => h("span", { class: "pill" }, h("span", { "aria-hidden": "true" }, icon), " ", text)));

/** Short overview shown next to the account form on the first run. */
export function overview(): HTMLElement {
  return h("section", { class: "card intro" },
    h("h2", {}, "Witaj w DORA 👋"),
    h("p", { class: "lead" }, "DORA pomaga przygotować sprawę nabywcy mieszkania przeciw deweloperowi o karę za opóźnienie. Wgrywasz dokumenty — po kilku minutach masz kartę sprawy, wyliczenie kary i projekt wezwania do zapłaty."),
    pills(),
    h("h3", {}, "Jak to wygląda"),
    h("ol", { class: "steps" },
      h("li", {}, "Wgrywasz PDF-y: umowę, aneksy, protokół odbioru, akt."),
      h("li", {}, "DORA ukrywa dane osobowe — Ty sprawdzasz i zatwierdzasz."),
      h("li", {}, "Dostajesz terminy, cenę, stawkę kary i wyliczenie, wszystko z cytatami."),
      h("li", {}, "Jednym kreatorem robisz pismo w Wordzie na szablonie kancelarii.")),
    h("p", { class: "muted small" }, "Zacznij od założenia konta obok. Po zalogowaniu poprowadzimy Cię krok po kroku."));
}

interface Onboarding { hidden?: boolean }

/** "Getting started" checklist on the cases page; ticks itself off and can be hidden. */
export async function startPanel(onChange: () => void): Promise<HTMLElement | null> {
  const state = (await v().get<Onboarding>("settings", "onboarding")) ?? {};
  if (state.hidden) return null;
  const [firm, profile, lawyers, templates, cases] = await Promise.all([getFirm(), getProfile(), listLawyers(), listTemplates(), listCases()]);
  const items: [boolean, string, string, string][] = [
    [Boolean(firm.name && firm.city), "Uzupełnij dane kancelarii", "nazwa, adres, rachunek, wzór sygnatury — trafiają do pism", "#/firm"],
    [Boolean(profile.lawyerId && lawyers.some((l) => l.id === profile.lawyerId)), "Dodaj siebie jako prawnika", "w tabeli prawników zaznacz „to ja”", "#/firm"],
    [templates.length > 1, "Wgraj własny szablon pisma (opcjonalnie)", "możesz zacząć od szablonu domyślnego", "#/templates"],
    [cases.length > 0, "Przeanalizuj pierwszą sprawę", "wgraj PDF-y i zatwierdź anonimizację", "#/new"],
  ];
  const done = items.filter(([ok]) => ok).length;
  const hide = async () => { await v().put("settings", "onboarding", { hidden: true }); onChange(); };
  return h("section", { class: "card intro" },
    h("div", { class: "row-between" }, h("h2", {}, `Jak zacząć (${done}/${items.length})`), button("Ukryj", () => void hide(), "link")),
    h("ul", { class: "checklist" }, ...items.map(([ok, title, hint, href]) =>
      h("li", ok ? { class: "done" } : {}, h("span", { class: "tick" }, ok ? "✓" : ""),
        h("span", {}, ok ? title : h("a", { href }, title), h("span", { class: "muted small" }, ` — ${hint}`))))),
    h("p", { class: "small" }, "Nie wiesz, od czego zacząć? Zajrzyj do ", h("a", { href: "#/help" }, "Instrukcji"), " — zajmie Ci to 3 minuty."));
}

const tile = (icon: string, title: string, text: string, href: string, cta: string) =>
  h("div", { class: "tile" }, h("div", { class: "tile-icon", "aria-hidden": "true" }, icon), h("h3", {}, title), h("p", {}, text),
    h("a", { class: "button secondary", href }, cta, " →"));

const step = (n: number, title: string, time: string, body: Child[], tip?: string) =>
  h("li", { class: "tl-step" }, h("span", { class: "num" }, String(n)),
    h("div", {}, h("h3", {}, title, " ", h("span", { class: "badge" }, time)), ...body, tip ? h("p", { class: "tip" }, h("strong", {}, "Wskazówka: "), tip) : null));

const faq = (q: string, ...a: Child[]) => h("details", { class: "faq" }, h("summary", {}, q), h("div", {}, ...a));

/** Full user guide (menu "Instrukcja"). */
export async function renderHelp(root: HTMLElement) {
  const state = (await v().get<Onboarding>("settings", "onboarding")) ?? {};
  const p = (...c: Child[]) => h("p", {}, ...c);

  root.replaceChildren(h("div", { class: "guide help" },
    h("section", { class: "hero" },
      h("h1", {}, "Jak pracować z DORA"),
      h("p", { class: "lead" }, "Od plików PDF do projektu wezwania do zapłaty — zwykle w kwadrans. Poniżej wszystko, co warto wiedzieć, w kolejności, w jakiej będziesz tego potrzebować."),
      pills()),

    h("h2", {}, "Zanim zaczniesz — raz, około 5 minut"),
    h("div", { class: "tiles" },
      tile("🏢", "Dane kancelarii", "Nazwa, adres, numer rachunku i termin zapłaty. Wpiszesz je raz — DORA wstawi je do każdego pisma.", "#/firm", "Uzupełnij"),
      tile("👤", "Ty i Twój zespół", "Dodaj prawników, którzy podpisują pisma. Przy swoim nazwisku zaznacz „to ja”.", "#/firm", "Dodaj prawników"),
      tile("📄", "Szablon pisma", "Masz gotowy szablon wezwania. Chcesz własny papier firmowy? Wgraj plik Word z polami {{…}}.", "#/templates", "Zobacz szablony")),

    h("h2", {}, "Jedna sprawa, krok po kroku"),
    h("ol", { class: "timeline" },
      step(1, "Wgraj dokumenty", "1 min", [
        p("Kliknij ", h("a", { href: "#/new" }, "Nowa sprawa"), ", wpisz nazwę (np. nazwisko klienta) i wybierz pliki PDF: umowę deweloperską, aneksy, protokół odbioru, akt przeniesienia własności."),
        p("Nie musisz mówić, który plik jest czym — DORA rozpozna to sama. Sygnatura nada się automatycznie."),
      ], "skany też działają. Program odczyta je sam (OCR), to po prostu potrwa chwilę dłużej."),
      step(2, "Sprawdź, co zostało ukryte", "1–2 min", [
        p("Zanim cokolwiek wyjdzie z komputera, DORA zamienia dane osobowe na znaczniki, np. ", h("code", {}, "Jan Kowalski → [NABYWCA_1]"), "."),
        p("Zobaczysz tabelę zamian i stronę oryginału obok wersji „po”. Jeśli wszystko gra — zaznacz pole i zatwierdź."),
      ], "jeśli widzisz w tekście po prawej coś, co powinno być ukryte, nie zatwierdzaj — przerwij i daj nam znać."),
      step(3, "Poczekaj na analizę", "1–3 min", [
        p("DORA czyta umowę i szuka terminów, ceny, stawki i limitu kary, wyłączeń odpowiedzialności oraz dat odbioru i aktu. Możesz w tym czasie zająć się czymś innym."),
      ]),
      step(4, "Przejrzyj kartę sprawy", "5 min", [
        p("Każde pole ma obok dosłowny cytat i numer strony, a z boku podgląd PDF. Sprawdzasz i klikasz ", h("kbd", {}, "Potwierdź"), " — albo poprawiasz wartość."),
        p("Pod kartą jest wyliczenie kary z pełnym wzorem oraz klauzule, które warto ocenić (np. limit kary, kara wyłączna)."),
      ], "kwotę i dni zawsze liczy program, nigdy sztuczna inteligencja — dlatego wynik jest powtarzalny i możesz go sprawdzić."),
      step(5, "Przygotuj pismo", "3 min", [
        p("Kliknij ", h("kbd", {}, "Pismo"), ", wybierz szablon i mocodawców. Kreator sam podpowie dewelopera, umowę, kwotę, rachunek i sygnaturę."),
        p("Poprawiasz, co chcesz, i pobierasz plik .docx. Dalej pracujesz w Wordzie jak zawsze."),
      ])),

    h("h2", {}, "Co oznaczają kolory i oznaczenia"),
    h("div", { class: "legend card" },
      h("div", {}, h("span", { class: "sample unconfirmed" }, "1 080 000,00 zł"), h("span", {}, "Czerwona ramka — pole czeka na Twoje potwierdzenie.")),
      h("div", {}, h("span", { class: "sample" }, "1 080 000,00 zł"), h("span", {}, "Bez ramki — pole potwierdzone przez Ciebie.")),
      h("div", {}, h("span", { class: "badge warn" }, "do sprawdzenia"), h("span", {}, "DORA nie znalazła cytatu w dokumencie — przyjrzyj się szczególnie uważnie.")),
      h("div", {}, h("span", { class: "sample empty" }, "—"), h("span", {}, "Puste pole — tej informacji nie ma w dokumentach. DORA nigdy nie zgaduje."))),

    h("h2", {}, "Często zadawane pytania"),
    h("div", { class: "faqs" },
      faq("Czy moje dokumenty trafiają do internetu?",
        p("Pliki PDF — nie. Odczyt, OCR i ukrywanie danych osobowych dzieją się w Twojej przeglądarce. Na serwer analizy idzie wyłącznie tekst po anonimizacji, który sam zatwierdzasz. Serwer dodatkowo odrzuca tekst, w którym znajdzie np. PESEL albo numer konta.")),
      faq("Gdzie są zapisane moje sprawy?",
        p("Tylko na tym komputerze, w tej przeglądarce, zaszyfrowane Twoim hasłem. Na innym komputerze ani w innej przeglądarce ich nie zobaczysz — chyba że przeniesiesz je kopią zapasową.")),
      faq("Nie pamiętam hasła. Co teraz?",
        p("Niestety hasła nie da się odzyskać — to cena za to, że nikt poza Tobą nie odczyta danych. Możesz odtworzyć dane z kopii zapasowej albo zacząć od nowa. Dlatego warto trzymać hasło w menedżerze haseł kancelarii.")),
      faq("Jak nie stracić danych?",
        p("Raz w tygodniu (albo po ważnej sprawie) kliknij ", h("a", { href: "#/backup" }, "Kopia zapasowa"), ". Plik jest zaszyfrowany, więc możesz go spokojnie trzymać na dysku kancelarii. Uwaga: wyczyszczenie danych przeglądarki usuwa sprawy.")),
      faq("Analiza znalazła złą wartość. Czy mogę ją poprawić?",
        p("Tak. Wpisz właściwą wartość w polu i kliknij ", h("kbd", {}, "Potwierdź"), ". „Wstaw z cytatu” przepisze kwotę lub datę wprost z cytatu, a „Przywróć z dokumentu” cofnie Twoją zmianę. Wyliczenie i pismo od razu korzystają z poprawionych danych.")),
      faq("Jak liczona jest liczba dni opóźnienia?",
        p("Od dnia po terminie z umowy (albo z aneksu, jeśli go zmienił) do faktycznej daty odbioru lub aktu — a jeśli jeszcze ich nie było, do „daty wyliczenia”, którą możesz zmienić i kliknąć ", h("kbd", {}, "Przelicz"), ". Cały wzór i dane wejściowe widzisz pod wyliczeniem.")),
      faq("Ile trwa analiza i czy mogę zamknąć kartę?",
        p("Zwykle 1–3 minuty, przy dużych skanach dłużej. Nie zamykaj karty w trakcie. Jeśli coś się przerwie, sprawa zostanie zapisana i na jej stronie będzie przycisk do ponowienia analizy.")),
      faq("Dlaczego DORA prosi o hasło?",
        p("Dla bezpieczeństwa DORA blokuje się:"),
        h("ul", {},
          h("li", {}, "po 30 minutach bez żadnej aktywności (kliknięcia, pisania, ruchu myszy, przewijania),"),
          h("li", {}, "po odświeżeniu strony (F5), zamknięciu karty lub przeglądarki — hasło jest pamiętane tylko w otwartej karcie,"),
          h("li", {}, "od razu, gdy klikniesz „Zablokuj” w menu — np. gdy odchodzisz od biurka.")),
        p("Wpisz hasło — wrócisz do tej samej strony. Niezapisane zmiany w otwartym formularzu przepadają, dlatego zapisuj kartę i pismo na bieżąco."))),

    h("section", { class: "card note" },
      h("h2", {}, "Czego DORA nie robi"),
      h("ul", {},
        h("li", {}, "Nie udziela porady prawnej. Przygotowuje projekt — decyzję podejmujesz Ty."),
        h("li", {}, "Nie przesądza, czy klauzula jest niedozwolona. Pokazuje sygnały do Twojej oceny."),
        h("li", {}, "Nie gwarantuje, że anonimizacja wyłapie wszystko. Dlatego zawsze ją zatwierdzasz."))),

    state.hidden
      ? h("p", {}, button("Pokaż znowu panel „Jak zacząć” na stronie Sprawy", async () => {
        await v().put("settings", "onboarding", { hidden: false });
        location.hash = "#/cases";
      }, "secondary"))
      : null));
}
