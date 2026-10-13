// Case page: case card with quotes, the lawyer's confirmations/corrections (saved with the case), calculation,
// clauses and the PDF preview. Personal data is restored locally from the case's token mapping.
import { calculateFromExtraction } from "../../../shared/adapter";
import { restore } from "../../../shared/anonymize";
import { dec, fmtDate, fmtPercent, formatPln, plnToGrosze } from "../../../shared/calculator";
import {
  CorrectionError, amountInQuote, applyCorrections, editValue, formatAmountInput, groupAmount, kindOf, parseValue,
  valueMatchesQuote, valuesEqual,
} from "../../../shared/corrections";
import library from "../../../shared/generated/clause_library.json";
import { ClauseFlag, Extraction, iterFields } from "../../../shared/schema";
import { type QuoteIssue, verifyClauseQuote, verifyExtraction } from "../../../shared/verify";
import { type CaseRecord, deleteCase, getCase, getCasePdf, listLawyers, saveCase } from "../store";
import { BASIS, DOC_TYPES, EVENTS, ISSUES, LABELS, button, h, input, labeled, selectEl } from "../ui";
import { errorText, runAnalysis } from "./newcase";

const titles = new Map(library.patterns.map((p) => [p.id, p]));
const BASIS_OPTIONS: [string, string][] = [
  ["percent_of_price_per_day", "% ceny za dzień"], ["fixed_per_day", "stała kwota za dzień"],
  ["statutory_interest", "odsetki ustawowe"], ["other", "inny sposób"], ["", "brak"],
];
const EVENT_OPTIONS: [string, string][] = [
  ["transfer_delay", "opóźnienie umowy przenoszącej"], ["handover_delay", "opóźnienie wydania lokalu"],
  ["handover_delay, transfer_delay", "oba opóźnienia"], ["", "brak"],
];
const BOOL_OPTIONS: [string, string][] = [["tak", "tak"], ["nie", "nie"], ["", "brak"]];

let pdfUrls: string[] = [];

export async function renderCase(root: HTMLElement, id: string) {
  pdfUrls.forEach((u) => URL.revokeObjectURL(u));
  pdfUrls = [];
  const record = await getCase(id);
  if (!record) { root.replaceChildren(h("p", { class: "alert error" }, "Nie znaleziono sprawy.")); return; }
  const lawyers = await listLawyers();
  const mapping = new Map(record.mapping);
  const show = (t: string | null | undefined) => (t ? restore(t, mapping) : t ?? "");
  const anonymized = new Map(record.documents.map((d) => [d.id, d.anon]));
  const fieldErrors = new Map<string, string>();

  const frame = h("iframe", { title: "Podgląd dokumentu" }) as HTMLIFrameElement;
  async function showPdf(docId: string | null, page: number | null) {
    const doc = record!.documents.find((d) => d.id === (docId ?? "doc_1")) ?? record!.documents[0];
    if (!doc) return;
    const bytes = await getCasePdf(record!.id, doc.id);
    if (!bytes) return;
    const url = URL.createObjectURL(new Blob([bytes.slice()], { type: "application/pdf" }));
    pdfUrls.push(url);
    frame.src = `${url}#page=${page ?? 1}`;
  }
  function quoteLink(quote: string, docId: string | null, page: number | null) {
    const a = h("a", { href: "#" }, `„${show(quote)}”`);
    a.addEventListener("click", (e) => { e.preventDefault(); void showPdf(docId, page); });
    return h("span", {}, a, h("span", { class: "muted small" }, ` (${docId ?? "doc_1"}, str. ${page ?? "?"})`));
  }

  // --- header: title, number, lawyer, actions -----------------------------------------------
  const titleInput = input("title", record.title);
  const numberInput = input("caseNumber", record.caseNumber);
  const lawyerSelect = selectEl("lawyer", [["", "— brak —"], ...lawyers.map((l) => [l.id, l.fullName] as [string, string])], record.lawyerId);
  const header = h("div", { class: "row-between" },
    h("div", { class: "row small" }, labeled("Sprawa", titleInput), labeled("Sygnatura", numberInput), labeled("Prawnik", lawyerSelect),
      button("Zapisz", async () => {
        record.title = titleInput.value.trim() || record.title;
        record.caseNumber = numberInput.value.trim();
        record.lawyerId = lawyerSelect.value;
        await saveCase(record);
      }, "secondary")),
    h("div", { class: "actions" },
      record.status === "ready" ? h("a", { class: "button", href: `#/case/${record.id}/letter` }, "Pismo") : null,
      deleteButton()));

  function deleteButton() {
    const confirm = h("input", { type: "checkbox" }) as HTMLInputElement;
    return h("span", { class: "row small" }, h("label", {}, confirm, " potwierdzam"),
      button("Usuń sprawę", async () => {
        if (!confirm.checked) { confirm.focus(); return; }
        await deleteCase(record!.id);
        location.hash = "#/cases";
      }, "danger"));
  }

  if (record.status !== "ready" || !record.analysis) {
    const retry = button("Spróbuj ponownie", () => void runAnalysis(root, record));
    root.replaceChildren(h("section", { class: "card" }, header,
      record.status === "error"
        ? h("div", {}, h("p", { class: "alert error" }, `Analiza nie powiodła się: ${errorText(record.errorCode)}`), retry)
        : h("div", {}, h("p", {}, "Analiza nie została ukończona."), retry)));
    return;
  }

  let originalEx: Extraction;
  let flags: ClauseFlag[];
  try {
    originalEx = Extraction.parse(record.analysis.extraction);
    flags = record.analysis.clauses.map((c) => ClauseFlag.parse(c));
  } catch {
    root.replaceChildren(h("p", { class: "alert error" }, "Zapisany wynik analizy jest niepoprawny — uruchom analizę ponownie."),
      button("Spróbuj ponownie", () => void runAnalysis(root, record)));
    return;
  }
  const corrections = new Map(record.corrections);
  const results = h("div", { class: "left" });
  root.replaceChildren(h("div", {}, header), h("div", { class: "split" }, results, h("aside", { class: "right" }, frame)));
  void showPdf("doc_1", 1);

  async function persist() {
    record!.corrections = [...corrections];
    await saveCase(record!);
  }

  function confirmField(path: string, raw: string) {
    const kind = kindOf(path)!;
    try {
      const value = parseValue(kind, raw);
      const f = Object.fromEntries(iterFields(originalEx))[path];
      let original = f?.value as unknown;
      if (path.startsWith("annex_deadlines") && original) original = (original as { date: string }).date;
      const shownOriginal = kind === "text" && typeof original === "string" ? show(original) : original;
      corrections.set(path, { value, confirmed: valuesEqual(value, shownOriginal) || valuesEqual(value, original) });
      fieldErrors.delete(path);
      void persist();
    } catch (e) {
      fieldErrors.set(path, e instanceof CorrectionError ? e.message : String(e));
    }
    draw();
  }

  function editor(path: string, value: unknown, quote: string | null, confirmed: boolean, manual: boolean) {
    const kind = kindOf(path);
    if (!kind) return h("td", {});
    let control: HTMLInputElement | HTMLSelectElement;
    if (kind === "basis") control = selectEl("v", BASIS_OPTIONS, String(value ?? ""));
    else if (kind === "events") control = selectEl("v", EVENT_OPTIONS, Array.isArray(value) ? [...value].sort().join(", ") : "");
    else if (kind === "bool") control = selectEl("v", BOOL_OPTIONS, value === true ? "tak" : value === false ? "nie" : "");
    else {
      const current = kind === "text" && typeof value === "string" ? show(value) : editValue(path, value);
      control = input("v", current, { placeholder: kind === "date" ? "DD.MM.RRRR" : kind === "cap" ? "np. 5% albo 20 000" : "" });
      if (kind === "amount") {
        control.setAttribute("inputmode", "decimal");
        control.addEventListener("input", () => { control.value = formatAmountInput(control.value); });
      }
    }
    if (!confirmed) control.classList.add("unconfirmed");
    const row = h("div", { class: "row" }, button("Potwierdź", () => confirmField(path, control.value.replace(/\.(\d{1,2})$/, ",$1"))));
    if (manual) row.append(button("Przywróć z dokumentu", () => { corrections.delete(path); void persist(); draw(); }, "secondary"));
    const cell = h("td", { class: "edit" }, control, row);
    const amount = path === "price_gross" && value === null ? amountInQuote(quote) : null;
    if (amount !== null) cell.append(button(`Wstaw z cytatu: ${groupAmount(amount)} zł`, () => confirmField(path, groupAmount(amount)), "secondary"));
    const err = fieldErrors.get(path);
    if (err) cell.append(h("div", { class: "alert error small" }, err));
    return cell;
  }

  function display(path: string, value: unknown, basis: string | null): string {
    if (value === null || value === undefined) return "—";
    if (path.startsWith("annex_deadlines")) {
      const a = value as { date: string; field: string; annex_no: number | null };
      return `${fmtDate(a.date)} (${a.field === "handover_deadline" ? "wydanie lokalu" : "umowa przenosząca"}, aneks${a.annex_no !== null ? ` nr ${a.annex_no}` : ""})`;
    }
    if (path === "price_gross") return formatPln(plnToGrosze(dec(value as number)));
    if (path === "penalty_rate") return basis === "fixed_per_day" ? `${formatPln(plnToGrosze(dec(value as number)))} / dzień` : `${fmtPercent(dec(value as number))} ceny / dzień`;
    if (path === "penalty_basis") return BASIS[value as string] ?? String(value);
    if (path === "penalty_cap") {
      const c = value as { type: string; value: number };
      return c.type === "percent" ? `${fmtPercent(dec(c.value))} ceny` : formatPln(plnToGrosze(dec(c.value)));
    }
    if (path === "penalty_events") return (value as string[]).map((e) => EVENTS[e] ?? e).join(", ") || "—";
    if (typeof value === "boolean") return value ? "tak" : "nie";
    if (/_date$|_deadline$/.test(path)) return fmtDate(value as string);
    return show(String(value));
  }

  function draw() {
    const scroll = window.scrollY;
    const ex = applyCorrections(originalEx, corrections);
    const verified = verifyExtraction(originalEx, anonymized);
    const needsReview = new Set([...verified.needsReview].filter((p) => !corrections.has(p)));
    const byPath = new Map<string, QuoteIssue[]>();
    for (const i of verified.issues) if (!corrections.has(i.path)) byPath.set(i.path, [...(byPath.get(i.path) ?? []), i]);

    const dateInput = input("asOf", record!.asOf, { type: "date" });
    const types = new Map(record!.analysis!.classification.map((c) => [c.document_id, c.type]));
    const confirmedCount = iterFields(ex).filter(([p]) => kindOf(p) && corrections.has(p)).length;
    const editableCount = iterFields(ex).filter(([p]) => kindOf(p)).length;
    results.replaceChildren(
      h("p", { class: "alert info" }, `Sprawdź każde pole z dokumentem (kliknij cytat) i kliknij „Potwierdź” — pola z czerwoną ramką nie są jeszcze sprawdzone. Sprawdzone: ${confirmedCount} z ${editableCount}.`),
      h("div", { class: "row small" }, labeled("Wyliczenie na dzień ", dateInput),
        button("Przelicz", async () => { if (dateInput.value) { record!.asOf = dateInput.value; await saveCase(record!); draw(); } }, "secondary")),
      h("p", { class: "muted small" }, "Dokumenty: " + record!.documents.map((d) => `${d.name} — ${DOC_TYPES[types.get(d.id) ?? "other"] ?? "?"}`).join("; ")));

    const basis = ex.penalty_basis.value;
    const tbody = h("tbody");
    const mismatched: string[] = [];
    for (const [path, f] of iterFields(ex)) {
      const label = LABELS[path] ?? (path.startsWith("annex") ? "Termin z aneksu" : "Wyłączenie odpowiedzialności");
      const c = corrections.get(path);
      const manual = !!c && !c.confirmed;
      const mismatch = manual && valueMatchesQuote(path, f.value, f.quote) === false;
      if (mismatch) mismatched.push(label);
      tbody.append(h("tr", needsReview.has(path) ? { class: "review" } : {},
        h("td", {}, label,
          needsReview.has(path) ? h("span", { class: "badge warn" }, "do sprawdzenia") : null,
          mismatch ? h("span", { class: "badge warn" }, "różni się od cytatu") : null,
          manual ? h("span", { class: "badge ok" }, "wpisane przez prawnika") : c ? h("span", { class: "badge ok" }, "potwierdzone") : null,
          ...(byPath.get(path) ?? []).map((i) => h("div", { class: "muted small" }, ISSUES[i.issue] + (i.found_page ? ` (str. ${i.found_page})` : "")))),
        h("td", {}, h("strong", {}, display(path, f.value, basis)), h("div", { class: "muted small" }, `pewność: ${f.confidence}`)),
        h("td", { class: "quote" },
          manual ? h("div", { class: "muted small" }, "Wartość wpisana ręcznie; cytat to odczyt z dokumentu.") : null,
          f.quote ? quoteLink(f.quote, f.document_id, f.page) : "—"),
        editor(path, f.value, f.quote, !!c, manual)));
    }
    results.append(h("section", { class: "card" }, h("h2", {}, "Karta sprawy"),
      h("table", { class: "grid fields" }, h("thead", {}, h("tr", {}, h("th", {}, "Pole"), h("th", {}, "Wartość"), h("th", {}, "Cytat"), h("th", {}, "Weryfikacja"))), tbody)));

    const calc = calculateFromExtraction(ex, record!.asOf, needsReview);
    const calcSection = h("section", { class: "card" }, h("h2", {}, "Wyliczenie kary"));
    if (mismatched.length) calcSection.append(h("p", { class: "alert warn" }, `Wartość wpisana ręcznie nie zgadza się z liczbą w cytacie z dokumentu: ${mismatched.join(", ")} — sprawdź, czy nie ma pomyłki.`));
    calc.blocking.forEach((b) => calcSection.append(h("p", { class: "alert error" }, b)));
    calc.warnings.forEach((w) => calcSection.append(h("p", { class: "alert warn" }, w)));
    if (calc.result) {
      for (const p of calc.result.penalties) {
        calcSection.append(h("h3", {}, p.event === "handover_delay" ? "Opóźnienie w wydaniu lokalu" : "Opóźnienie w zawarciu umowy przenoszącej"));
        calcSection.append(h("table", { class: "grid" }, h("tbody", {}, ...p.steps.map((st) =>
          h("tr", {}, h("td", {}, st.label), h("td", {}, st.formula), h("td", {}, st.result))))));
        p.warnings.forEach((w) => calcSection.append(h("p", { class: "alert warn small" }, w)));
      }
      calc.result.skipped.forEach((sk) => calcSection.append(h("p", { class: "alert warn" }, `Nie wyliczono: ${sk}`)));
      calcSection.append(h("table", { class: "grid totals" }, h("tbody", {},
        h("tr", {}, h("th", {}, "Razem bez limitu"), h("td", {}, formatPln(calc.result.totalUncapped))),
        h("tr", {}, h("th", {}, "Razem z limitem umownym"), h("td", {}, formatPln(calc.result.totalCapped))))));
      calcSection.append(h("h3", {}, "Oś czasu"), h("ol", { class: "timeline" }, ...calc.result.timeline.map((t) =>
        h("li", { class: `kind-${t.kind}` }, h("strong", {}, fmtDate(t.date)), ` ${t.label}`))));
      calcSection.append(h("p", {}, h("a", { class: "button", href: `#/case/${record!.id}/letter` }, "Przygotuj pismo")));
    }
    results.append(calcSection);

    const clauseSection = h("section", { class: "card" }, h("h2", {}, "Klauzule do oceny"));
    if (!flags.length) clauseSection.append(h("p", {}, "Nie wskazano klauzul pasujących do wzorców z biblioteki."));
    for (const cf of flags) {
      const pattern = titles.get(cf.clause_id);
      const issue = verifyClauseQuote(cf.quote, cf.page, cf.document_id, anonymized);
      clauseSection.append(h("article", { class: issue ? "clause review" : "clause" },
        h("h3", {}, pattern?.title ?? cf.clause_id, " ", h("span", { class: "badge" }, cf.confidence),
          issue ? h("span", { class: "badge warn" }, `cytat do sprawdzenia: ${ISSUES[issue]}`) : null),
        h("blockquote", {}, quoteLink(cf.quote, cf.document_id, cf.page)),
        h("p", {}, show(cf.reasoning)),
        h("p", { class: "muted small" }, `Źródło wzorca: ${pattern?.source || "brak"}${pattern && !pattern.verified ? " · niezweryfikowane" : ""}`)));
    }
    results.append(clauseSection);
    window.scrollTo(0, scroll);
  }

  draw();
}

/** Current extraction of a case with the lawyer's corrections (used by the letter wizard). */
export function caseExtraction(record: CaseRecord): Extraction {
  return applyCorrections(Extraction.parse(record.analysis!.extraction), new Map(record.corrections));
}
