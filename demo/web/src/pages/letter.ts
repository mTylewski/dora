// Letter wizard: letter type (template) -> clients from the documents -> developer and agreement -> firm -> amount
// -> edit the text -> .docx filled in the browser. Only anonymized facts go to the server (justification paragraph).
import { calculateFromExtraction, letterFacts, unsupportedNumbers } from "../../../shared/adapter";
import { anonymizePages, restore } from "../../../shared/anonymize";
import { fmtDate, formatPln } from "../../../shared/calculator";
import { type LetterParties, PLACEHOLDERS, letterValues, missingFields, penaltyRows } from "../../../shared/letter";
import { verifyExtraction } from "../../../shared/verify";
import { ApiError, requestJustification } from "../api";
import { fillTemplate, templatePlaceholders } from "../docx";
import { type CaseRecord, getCase, getFirm, listLawyers, listTemplates, saveCase, templateBytes } from "../store";
import { ERRORS, ROLE_LABELS, button, download, h, input, labeled, progressBox, safeFileName, selectEl, todayIso } from "../ui";
import { caseExtraction } from "./case";

function calculation(record: CaseRecord) {
  const ex = caseExtraction(record);
  const verified = verifyExtraction(ex, new Map(record.documents.map((d) => [d.id, d.anon])));
  const corrected = new Set(record.corrections.map(([p]) => p));
  const needsReview = new Set([...verified.needsReview].filter((p) => !corrected.has(p)));
  return { ex, calc: calculateFromExtraction(ex, record.asOf, needsReview) };
}

export async function renderLetter(root: HTMLElement, caseId: string, fresh = false) {
  const record = await getCase(caseId);
  if (!record?.analysis) { root.replaceChildren(h("p", { class: "alert error" }, "Sprawa nie ma wyniku analizy.")); return; }
  if (record.letter && !fresh) return renderEditor(root, record);
  return renderWizard(root, record);
}

async function renderWizard(root: HTMLElement, record: CaseRecord, error?: string) {
  const [templates, lawyers, firm] = await Promise.all([listTemplates(), listLawyers(), getFirm()]);
  const mapping = new Map(record.mapping);
  const show = (t: string | null | undefined) => (t ? restore(t, mapping) : "");
  const { ex, calc } = calculation(record);
  const saved = (record.letterForm ?? {}) as Record<string, unknown>;
  const back = h("a", { href: `#/case/${record.id}` }, "← wróć do sprawy");

  if (!calc.result) {
    root.replaceChildren(h("section", { class: "card" }, h("h1", {}, "Pismo"), h("p", { class: "alert error" }, "Brak wyliczenia — uzupełnij kartę sprawy."), back));
    return;
  }

  // 1. letter type
  const templateRadios = templates.map((t, i) => {
    const r = h("input", { type: "radio", name: "template", value: t.id }) as HTMLInputElement;
    if ((saved.templateId ?? templates[templates.length - 1].id) === t.id || (!saved.templateId && i === templates.length - 1)) r.checked = true;
    return h("label", { class: "row option" }, r, h("span", {}, h("strong", {}, t.name), t.description ? h("br") : null, t.description ? h("span", { class: "muted small" }, t.description) : null));
  });

  // 2. clients
  // Cases saved before role detection improved: recognize roles again from the stored text (locally, same tokens).
  if (!record.persons.some((p) => p.role === "buyer") && record.documents.length) {
    const fresh = anonymizePages(new Map(record.documents.map((d) => [d.id, d.pages]))).persons;
    if (fresh.some((p) => p.role === "buyer")) { record.persons = fresh; await saveCase(record); }
  }
  // Buyers from the documents; if no role was recognized, persons without a role (the lawyer confirms).
  const buyers = record.persons.filter((p) => p.role === "buyer");
  const savedClients = (saved.clients as { name: string; address: string; include: boolean }[] | undefined)?.filter((c) => c.name);
  const guessed = !buyers.length && record.persons.some((p) => !p.role);
  const suggested = savedClients?.length ? savedClients
    : (buyers.length ? buyers : record.persons.filter((p) => !p.role)).map((p) => ({ name: p.name, address: p.address ?? "", include: true }));
  const clientsHint = savedClients?.length ? null
    : buyers.length ? h("p", { class: "muted small" }, "Zaznaczono nabywców wskazanych w umowie. Sprawdź, czy wszyscy są mocodawcami.")
    : guessed ? h("p", { class: "alert warn" }, "Nie rozpoznano, kto w umowie jest nabywcą. Zaznaczono osoby bez ustalonej roli — odznacz te, które nie są mocodawcami.")
    : h("p", { class: "alert warn" }, "W dokumentach nie znaleziono nabywców. Wpisz mocodawców ręcznie.");
  const clientRows = h("div", { class: "stack" });
  const addClientRow = (c: { name: string; address: string; include: boolean }) => {
    const include = h("input", { type: "checkbox", title: "uwzględnij w piśmie" }) as HTMLInputElement;
    include.checked = c.include;
    clientRows.append(h("div", { class: "row client" }, include, input("clientName", c.name, { placeholder: "imię i nazwisko" }),
      input("clientAddress", c.address, { placeholder: "adres", class: "wide" })));
  };
  [...suggested, { name: "", address: "", include: false }, { name: "", address: "", include: false }].forEach(addClientRow);
  const picker = h("div", { class: "person-picker" }, h("div", { class: "muted small" }, "Osoby znalezione w dokumentach — kliknij, aby dodać:"),
    ...record.persons.map((p) => button(`${p.name} — ${p.role ? ROLE_LABELS[p.role] ?? p.role : "rola nieustalona"}${p.address ? `, ${p.address}` : ""}`, () => {
      const rows = [...clientRows.querySelectorAll<HTMLElement>(".client")];
      if (rows.some((r) => r.querySelector<HTMLInputElement>('input[name="clientName"]')!.value === p.name)) return;
      const empty = rows.find((r) => !r.querySelector<HTMLInputElement>('input[name="clientName"]')!.value);
      if (empty) {
        empty.querySelector<HTMLInputElement>('input[name="clientName"]')!.value = p.name;
        empty.querySelector<HTMLInputElement>('input[name="clientAddress"]')!.value = p.address ?? "";
        empty.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked = true;
      } else addClientRow({ name: p.name, address: p.address ?? "", include: true });
    }, "secondary chip")));

  // 3. developer and agreement
  const developerName = input("developerName", (saved.developerName as string) ?? show(ex.developer_name.value));
  const developerAddress = input("developerAddress", (saved.developerAddress as string) ?? "", { placeholder: "adres siedziby / do doręczeń" });
  const agreementDate = input("agreementDate", (saved.agreementDate as string) ?? (ex.agreement_date.value ? fmtDate(ex.agreement_date.value) : ""), { placeholder: "DD.MM.RRRR" });
  const agreementDeed = input("agreementDeed", (saved.agreementDeed as string) ?? show(ex.agreement_reference.value), { placeholder: "Rep. A nr …" });

  // 4. firm
  const caseNumber = input("caseNumber", record.caseNumber);
  const lawyer = selectEl("lawyer", [["", "— wybierz —"], ...lawyers.filter((l) => l.active).map((l) => [l.id, `${l.fullName}, ${l.title}`] as [string, string])], (saved.lawyerId as string) ?? record.lawyerId);
  const bank = input("bank", (saved.bankAccount as string) ?? firm.bankAccount, { class: "wide" });
  const days = input("days", String((saved.days as number) ?? firm.paymentDeadlineDays), { type: "number", min: "1" });

  // 5. amount
  const cappedYes = h("input", { type: "radio", name: "capped", value: "yes" }) as HTMLInputElement;
  const cappedNo = h("input", { type: "radio", name: "capped", value: "no" }) as HTMLInputElement;
  (saved.capped ? cappedYes : cappedNo).checked = true;

  const prepare = button("Przygotuj projekt pisma", () => void run());
  root.replaceChildren(h("section", { class: "card" },
    h("div", { class: "row-between" }, h("h1", {}, `Nowe pismo — ${record.title}${record.caseNumber ? ` (${record.caseNumber})` : ""}`), back),
    h("p", { class: "muted" }, "Dane są podpowiedziane z dokumentów sprawy i ustawień kancelarii — sprawdź je. Dane osobowe zostają na tym komputerze; usługa AI przygotowuje wyłącznie projekt uzasadnienia na podstawie faktów bez danych osobowych."),
    !firm.name || !firm.city ? h("p", { class: "alert warn" }, "Uzupełnij dane kancelarii (nazwa, miejscowość) w zakładce Kancelaria — inaczej w piśmie zostaną puste pola.") : null,
    error ? h("p", { class: "alert error" }, error) : null,
    h("div", { class: "stack wizard" },
      h("fieldset", {}, h("legend", {}, "1. Rodzaj pisma"), ...templateRadios, h("p", { class: "small" }, h("a", { href: "#/templates" }, "Dodaj własny szablon pisma"))),
      h("fieldset", {}, h("legend", {}, "2. Mocodawcy (klienci)"), clientsHint ?? "", picker, clientRows),
      h("fieldset", {}, h("legend", {}, "3. Deweloper i umowa"), labeled("Deweloper", developerName), labeled("Adres dewelopera", developerAddress),
        h("div", { class: "row" }, labeled("Data umowy deweloperskiej", agreementDate), labeled("Numer aktu notarialnego", agreementDeed))),
      h("fieldset", {}, h("legend", {}, "4. Kancelaria"), h("div", { class: "row" }, labeled("Sygnatura sprawy", caseNumber), labeled("Prawnik podpisujący", lawyer)),
        h("div", { class: "row" }, labeled("Rachunek do zapłaty", bank), labeled("Termin zapłaty (dni)", days))),
      h("fieldset", {}, h("legend", {}, "5. Kwota żądania"),
        h("label", { class: "row" }, cappedNo, ` bez limitu umownego: ${formatPln(calc.result.totalUncapped)}`),
        h("label", { class: "row" }, cappedYes, ` z limitem umownym: ${formatPln(calc.result.totalCapped)}`)),
      prepare)));

  async function run() {
    const templateId = templateRadios.map((l) => l.querySelector<HTMLInputElement>("input")!).find((r) => r.checked)?.value ?? templates[0].id;
    const template = templates.find((t) => t.id === templateId)!;
    const clients = [...clientRows.querySelectorAll<HTMLElement>(".client")].map((r) => ({
      name: r.querySelector<HTMLInputElement>('input[name="clientName"]')!.value.trim(),
      address: r.querySelector<HTMLInputElement>('input[name="clientAddress"]')!.value.trim(),
      include: r.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked,
    })).filter((c) => c.name);
    const capped = cappedYes.checked;
    const chosenLawyer = lawyers.find((l) => l.id === lawyer.value);
    record.letterForm = {
      templateId, clients, developerName: developerName.value, developerAddress: developerAddress.value,
      agreementDate: agreementDate.value, agreementDeed: agreementDeed.value, lawyerId: lawyer.value,
      bankAccount: bank.value, days: Number(days.value) || firm.paymentDeadlineDays, capped,
    };
    record.caseNumber = caseNumber.value.trim();
    await saveCase(record);

    const progress = progressBox();
    root.replaceChildren(progress.el);
    progress.set("Przygotowanie pisma", "Odczyt szablonu…", 10);
    try {
      const bytes = await templateBytes(templateId);
      const found = await templatePlaceholders(bytes);
      const penalties = calc.result!.penalties;
      let justification = "";
      const warnings: string[] = [];
      if (found.has("justification")) {
        progress.set("Przygotowanie pisma", "Projekt uzasadnienia (usługa AI, tylko fakty bez danych osobowych)…", 40);
        const facts = letterFacts(ex, penalties, capped); // anonymized: tokens, dates, amounts
        const text = await requestJustification(facts);
        const unknown = unsupportedNumbers(text, facts);
        if (unknown.length) warnings.push(`Uzasadnienie zawiera liczby spoza danych sprawy: ${unknown.join(", ")} — sprawdź.`);
        justification = restore(text, mapping);
      }
      const included = clients.filter((c) => c.include);
      const parties: LetterParties = {
        clients: included.map((c) => [c.name, c.address]), clientName: included.map((c) => c.name).join(" i "),
        clientAddress: included[0]?.address ?? "",
        developerName: developerName.value.trim(), developerAddress: developerAddress.value.trim(),
        agreementDate: agreementDate.value.trim(), agreementDeed: agreementDeed.value.trim(),
        bankAccount: bank.value.trim(), caseNumber: caseNumber.value.trim(),
        lawyerName: chosenLawyer?.fullName ?? "", lawyerTitle: chosenLawyer?.title ?? "", lawyerRegistry: chosenLawyer?.registryNo ?? "",
        firmName: firm.name, firmAddress: firm.address, city: firm.city,
        paymentDeadlineDays: Number(days.value) || firm.paymentDeadlineDays, legalBasis: firm.legalBasis,
      };
      const total = capped ? calc.result!.totalCapped : calc.result!.totalUncapped;
      record.letter = {
        templateId, templateName: template.name,
        values: letterValues(parties, total, justification, todayIso()),
        rows: penaltyRows(penalties, capped), totalGrosze: String(total), capped,
        preparedAt: new Date().toISOString(), warnings,
      };
      await saveCase(record);
      await renderEditor(root, record);
    } catch (e) {
      const code = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      await renderWizard(root, record, `Nie udało się przygotować pisma: ${ERRORS[code] ?? code}`);
    }
  }
}

async function renderEditor(root: HTMLElement, record: CaseRecord, notice?: string) {
  const draft = record.letter!;
  const { calc } = calculation(record);
  const current = calc.result ? (draft.capped ? calc.result.totalCapped : calc.result.totalUncapped) : null;
  const stale = current === null || String(current) !== draft.totalGrosze;
  let found: Set<string>;
  try { found = await templatePlaceholders(await templateBytes(draft.templateId)); } catch { found = new Set(Object.keys(PLACEHOLDERS)); }
  const keys = Object.keys(PLACEHOLDERS).filter((k) => found.has(k));
  const longFields = new Set(["intro", "demand", "justification", "legal_basis", "closing", "clients", "agreement"]);
  const editors = new Map<string, HTMLInputElement | HTMLTextAreaElement>();
  const fields = keys.map((k) => {
    const control = longFields.has(k)
      ? h("textarea", { rows: k === "justification" ? "12" : "3" }, draft.values[k] ?? "") as HTMLTextAreaElement
      : input(k, draft.values[k] ?? "");
    editors.set(k, control);
    return labeled(PLACEHOLDERS[k], control);
  });
  const rowsTable = h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ...["Tytuł", "Okres opóźnienia", "Dni", "Kwota"].map((t) => h("th", {}, t)))),
    h("tbody", {}, ...draft.rows.map((r) => h("tr", {}, ...r.map((c) => h("td", {}, c))))));
  const missing = missingFields(draft.values);

  async function save() {
    for (const [k, el] of editors) draft.values[k] = el.value.replace(/\r\n/g, "\n").trim();
    draft.savedAt = new Date().toISOString();
    await saveCase(record);
  }
  async function downloadDocx() {
    await save();
    const blob = await fillTemplate(await templateBytes(draft.templateId), draft.values, draft.rows);
    download(blob, `${safeFileName(`${draft.templateName}_${record.caseNumber}`)}_PROJEKT.docx`);
  }

  const discardConfirm = h("input", { type: "checkbox" }) as HTMLInputElement;
  root.replaceChildren(h("section", { class: "card letter-edit" },
    h("div", { class: "row-between" }, h("h1", {}, `${draft.templateName} — ${record.title}${record.caseNumber ? ` (${record.caseNumber})` : ""}`), h("a", { href: `#/case/${record.id}` }, "← wróć do sprawy")),
    h("p", { class: "muted" }, `Przygotowano ${draft.preparedAt.slice(0, 16).replace("T", " ")}${draft.savedAt ? ` · ostatni zapis ${draft.savedAt.slice(0, 16).replace("T", " ")}` : ""}. Kwota żądania: ${formatPln(BigInt(draft.totalGrosze))} (${draft.capped ? "z limitem umownym" : "bez limitu umownego"}).`),
    notice ? h("p", { class: "alert info" }, notice) : null,
    stale ? h("p", { class: "alert error" }, `Wyliczenie w sprawie zmieniło się od przygotowania projektu (teraz: ${current !== null ? formatPln(current) : "brak"}). Przygotuj pismo od nowa.`) : null,
    ...draft.warnings.map((w) => h("p", { class: "alert warn" }, w)),
    missing.length ? h("p", { class: "alert warn" }, `Do uzupełnienia: ${missing.join(", ")}`) : null,
    h("div", { class: "stack" }, ...fields,
      h("div", {}, h("p", { class: "small muted" }, "Wyliczenie kary (z kalkulatora, bez edycji — kwoty zmieniasz w karcie sprawy):"), rowsTable),
      h("p", { class: "muted small" }, "Akapity rozdzielaj pustą linią. Treść stałą pisma zawiera szablon."),
      h("div", { class: "row" },
        button("Zapisz", async () => { await save(); await renderEditor(root, record, "Zapisano zmiany."); }),
        button("Zapisz i pobierz .docx", () => void downloadDocx(), "secondary"))),
    h("div", { class: "row" },
      button("Nowe pismo / przygotuj od nowa", () => void renderLetter(root, record.id, true), "secondary"),
      h("label", { class: "small" }, discardConfirm, " potwierdzam"),
      button("Usuń projekt", async () => {
        if (!discardConfirm.checked) { discardConfirm.focus(); return; }
        record.letter = undefined;
        await saveCase(record);
        await renderLetter(root, record.id, true);
      }, "danger"))));
}
