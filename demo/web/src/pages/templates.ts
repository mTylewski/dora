// Letter templates: the firm's own .docx files with {{placeholders}} (stored encrypted on this computer).
import { PLACEHOLDERS, TABLE_PLACEHOLDER, letterValues } from "../../../shared/letter";
import { checkTemplate } from "../docx";
import { DEFAULT_TEMPLATE_ID, deleteTemplate, listTemplates, saveTemplate, templateBytes } from "../store";
import { button, download, h, input, labeled, safeFileName, uid } from "../ui";

export async function renderTemplates(root: HTMLElement, notice?: { ok?: string; errors?: string[]; warnings?: string[] }) {
  const templates = await listTemplates();
  const tbody = h("tbody");
  for (const t of templates) {
    const confirm = h("input", { type: "checkbox" }) as HTMLInputElement;
    tbody.append(h("tr", {},
      h("td", {}, h("strong", {}, t.name)), h("td", { class: "small" }, t.description),
      h("td", { class: "row" },
        button("Pobierz", async () => download(new Blob([await templateBytes(t.id)]), `${safeFileName(t.name)}.docx`), "secondary"),
        t.id === DEFAULT_TEMPLATE_ID ? null : h("span", { class: "row small" }, h("label", {}, confirm, " potwierdzam"),
          button("Usuń", async () => {
            if (!confirm.checked) { confirm.focus(); return; }
            await deleteTemplate(t.id);
            await renderTemplates(root);
          }, "danger")))));
  }

  const name = input("name", "", { maxlength: "200", placeholder: "np. Ostateczne wezwanie do zapłaty" });
  const description = input("description", "", { maxlength: "500" });
  const file = input("file", "", { type: "file", accept: ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
  const upload = button("Wgraj szablon", async () => {
    const f = file.files?.[0];
    if (!name.value.trim()) { name.focus(); return; }
    if (!f) { file.focus(); return; }
    const bytes = new Uint8Array(await f.arrayBuffer());
    const check = await checkTemplate(bytes);
    if (check.errors.length) { await renderTemplates(root, { errors: check.errors, warnings: check.warnings }); return; }
    await saveTemplate({ id: uid(), name: name.value.trim(), description: description.value.trim(), createdAt: new Date().toISOString() }, bytes);
    await renderTemplates(root, { ok: `Dodano szablon „${name.value.trim()}”.`, warnings: check.warnings });
  });

  root.replaceChildren(h("div", {},
    h("h1", {}, "Szablony pism"),
    notice?.ok ? h("p", { class: "alert info" }, notice.ok) : null,
    ...(notice?.errors ?? []).map((e) => h("p", { class: "alert error" }, e)),
    ...(notice?.warnings ?? []).map((w) => h("p", { class: "alert warn" }, w)),
    h("section", { class: "card" },
      h("p", {}, "Każdy szablon to jeden rodzaj pisma do wyboru w kreatorze (np. „Wezwanie przedsądowe”, „Odpowiedź na stanowisko dewelopera”). Treść stałą przygotowuje kancelaria w szablonie; program uzupełnia pola danymi sprawy."),
      h("table", { class: "grid" }, h("thead", {}, h("tr", {}, h("th", {}, "Rodzaj pisma"), h("th", {}, "Opis"), h("th", {}, ""))), tbody)),
    h("section", { class: "card" }, h("h2", {}, "Dodaj szablon"),
      h("div", { class: "stack" }, labeled("Nazwa rodzaju pisma", name), labeled("Opis (kiedy go używać)", description), labeled("Plik .docx", file), upload)),
    templateGuide()));
}

// --- step-by-step guide for preparing a template in Word ------------------------------------------

const GROUPS: [string, string[]][] = [
  ["Kancelaria, sprawa i podpis", ["firm_name", "firm_address", "place_and_date", "letter_date", "case_number", "lawyer", "lawyer_name", "lawyer_title", "lawyer_registry", "draft_banner"]],
  ["Strony", ["client_names", "clients", "developer_name", "developer_address"]],
  ["Umowa deweloperska", ["agreement", "agreement_date", "agreement_deed"]],
  ["Kwota i zapłata", ["total_amount", "payment_deadline_days", "bank_account"]],
  ["Gotowe akapity (najlepiej każdy w osobnym akapicie)", ["intro", "demand", "justification", "legal_basis", "closing"]],
];

/** Example values produced by the same code that fills real letters (fictitious data). */
function exampleValues(): Record<string, string> {
  return letterValues({
    clients: [["Jan Przykładowy", "ul. Próbna 1, 00-001 Warszawa"]], clientName: "Jan Przykładowy",
    developerName: "APM Przykład sp. z o.o.", developerAddress: "ul. Budowlana 2, 00-002 Warszawa",
    agreementDate: "06.02.2026", agreementDeed: "Rep. A nr 418/2026", bankAccount: "11 1111 1111 1111 1111 1111 1111",
    caseNumber: "KAN/2026/001", lawyerName: "Anna Prawnicza", lawyerTitle: "radca prawny", lawyerRegistry: "WA-1234",
    firmName: "Kancelaria Przykładowa", firmAddress: "ul. Kancelaryjna 3, 00-003 Warszawa", city: "Warszawa",
    paymentDeadlineDays: 14, legalBasis: "(tekst podstawy prawnej z zakładki Kancelaria)",
  }, 680400n, "(akapit uzasadnienia przygotowany przez usługę AI na podstawie dat i kwot — do edycji przed pobraniem)", "2026-10-06");
}

const code = (text: string) => h("code", {}, text);
const field = (name: string) => code(`{{${name}}}`);

function templateGuide() {
  const ex = exampleValues();
  const groups = GROUPS.map(([title, keys]) => h("div", {},
    h("h3", {}, title),
    h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, h("th", {}, "Wpisz w szablonie"), h("th", {}, "Co to jest"), h("th", {}, "Przykład — co pojawi się w piśmie"))),
      h("tbody", {}, ...keys.map((k) => h("tr", {}, h("td", {}, field(k)), h("td", {}, PLACEHOLDERS[k]), h("td", { class: "small" }, ex[k] || "—")))))));

  const step = (n: number, ...content: (Node | string)[]) => h("li", {}, h("strong", {}, `Krok ${n}. `), ...content);
  const templateText = [
    "Sygn.: {{case_number}}", "{{place_and_date}}", "", "{{developer_name}}", "{{developer_address}}", "",
    "PRZEDSĄDOWE WEZWANIE DO ZAPŁATY", "", "{{intro}}", "",
    "Wzywam do zapłaty kwoty {{total_amount}} w terminie {{payment_deadline_days}} dni na rachunek nr {{bank_account}}.", "", "{{lawyer}}",
  ].join("\n");
  const filledText = templateText.replace(/\{\{(\w+)\}\}/g, (m, k: string) => ex[k] ?? m);

  return h("section", { class: "card guide" },
    h("h2", {}, "Jak przygotować własny szablon pisma"),
    h("p", {}, "Szablon to zwykły dokument Word (.docx) — np. wezwanie na papierze firmowym kancelarii — w którym w miejscach na dane sprawy wpisujesz ",
      h("strong", {}, "pola"), ". Pole to nazwa w podwójnych nawiasach klamrowych, np. ", field("case_number"),
      ". Przy tworzeniu pisma program zamienia każde pole na dane sprawy, a całą resztę dokumentu (formułki, pouczenia, logo, stopkę) zostawia bez zmian."),

    h("h3", {}, "Krok po kroku"),
    h("ol", { class: "steps" },
      step(1, "Otwórz w Wordzie dokument, którego zwykle używasz (papier firmowy, Wasz wzór wezwania). Możesz też zacząć od szablonu domyślnego — kliknij „Pobierz” przy nim w tabeli powyżej."),
      step(2, "W każdym miejscu, w którym ma się pojawić dana ze sprawy, usuń przykładowy tekst i wpisz nazwę pola z listy na dole strony, razem z nawiasami, np. ",
        field("case_number"), ". Nawiasy klamrowe wpiszesz, przytrzymując Shift i naciskając klawisze ", h("kbd", {}, "["), " i ", h("kbd", {}, "]"), " (obok litery P)."),
      step(3, "Jeśli pismo ma zawierać tabelę z wyliczeniem kary — przygotuj ją jak opisano niżej („Tabela z wyliczeniem”)."),
      step(4, "Zapisz plik jako dokument Word: Plik → Zapisz jako → typ „Dokument programu Word (*.docx)”."),
      step(5, "Wróć tutaj, w części „Dodaj szablon” wpisz nazwę rodzaju pisma (np. „Ostateczne wezwanie do zapłaty”), krótki opis, wybierz plik i kliknij „Wgraj szablon”. Program sprawdzi plik i pokaże ostrzeżenia, jeśli coś jest nie tak."),
      step(6, "Sprawdź efekt: w dowolnej sprawie kliknij „Pismo”, wybierz nowy rodzaj pisma, przygotuj projekt i pobierz .docx. Otwórz plik w Wordzie i porównaj z szablonem.")),

    h("h3", {}, "Przykład"),
    h("div", { class: "compare" },
      h("div", {}, h("div", { class: "muted small" }, "Tak wpisujesz w szablonie (Word)"), h("pre", { class: "page" }, templateText)),
      h("div", {}, h("div", { class: "muted small" }, "Tak wygląda gotowe pismo"), h("pre", { class: "page sent" }, filledText))),
    h("p", { class: "muted small" }, "Możesz używać pojedynczych danych (np. kwota, rachunek) we własnych zdaniach albo gotowych akapitów (np. ", field("demand"),
      " — całe zdanie z żądaniem zapłaty). Każde pole można użyć dowolnie wiele razy, także w nagłówku i stopce dokumentu."),

    h("h3", {}, "Tabela z wyliczeniem — pole ", field(TABLE_PLACEHOLDER)),
    h("ol", {},
      h("li", {}, "Wstaw w Wordzie tabelę z 4 kolumnami i 2 wierszami (Wstawianie → Tabela)."),
      h("li", {}, "W pierwszym wierszu wpisz nagłówki, np. „Tytuł”, „Okres opóźnienia”, „Dni”, „Kwota”."),
      h("li", {}, "W drugim wierszu, w pierwszej komórce, wpisz ", field(TABLE_PLACEHOLDER), ". Pozostałe trzy komórki zostaw puste."),
      h("li", {}, "Program powieli drugi wiersz dla każdego opóźnienia i wpisze: rodzaj opóźnienia, okres, liczbę dni i kwotę. Formatowanie komórek (czcionka, obramowanie) zostaje.")),

    h("h3", {}, "Na co uważać"),
    h("ul", {},
      h("li", {}, "Nazwę pola wpisz dokładnie jak w tabeli: małymi literami, z podkreślnikami, bez spacji i bez polskich znaków. Dobrze: ", field("case_number"),
        ". Źle: ", code("{{ case number }}"), ", ", code("{{Sygnatura}}"), ", ", code("{case_number}"), "."),
      h("li", {}, "Akapit, w którym jest pole, dostaje jednolite formatowanie — takie jak jego początek. Jeśli w jednym zdaniu część ma być pogrubiona, a część nie, wstaw pole w osobnym akapicie albo pogrub cały akapit."),
      h("li", {}, "Długie pola (", field("intro"), ", ", field("demand"), ", ", field("justification"), ", ", field("legal_basis"), ", ", field("closing"),
        ") wstawiaj każde w osobnym akapicie — mogą mieć kilka zdań lub akapitów."),
      h("li", {}, "Pole ", field("justification"), " oznacza, że program poprosi usługę AI o projekt akapitu uzasadnienia (tylko na podstawie dat i kwot, bez danych osobowych). Jeśli go nie wstawisz, pismo zostanie wypełnione wyłącznie danymi."),
      h("li", {}, "Pole ", field("draft_banner"), " wstawia napis „PROJEKT — do weryfikacji i podpisu”. Warto je mieć na górze, żeby projekt nie został wysłany przez pomyłkę — usuwasz je przed podpisaniem."),
      h("li", {}, "Jeśli po wgraniu program pokaże „Nieznane pole”, to najczęściej literówka w nazwie pola — popraw ją w Wordzie i wgraj plik jeszcze raz."),
      h("li", {}, "Brakujące dane (np. niepodany rachunek) pojawią się w piśmie jako ", code("[UZUPEŁNIJ: …]"), " — łatwo je odszukać w Wordzie (Ctrl+F).")),

    h("h3", {}, "Wszystkie pola"),
    ...groups);
}
