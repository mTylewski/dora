// New case: read PDFs and anonymize on this computer, let the lawyer approve, send only the anonymized text,
// save the case (encrypted, locally) with the result.
import { type Anonymizer, type Person, anonymizePages, suspiciousWords } from "../../../shared/anonymize";
import { ApiError, analyzeText, inviteState } from "../api";
import { readPdfText } from "../pdftext";
import { type CaseDoc, type CaseRecord, getFirm, getProfile, listCases, listLawyers, nextCaseNumber, saveCase, saveCasePdf } from "../store";
import { ERRORS, LABEL_NAMES, button, h, input, inviteSummary, labeled, progressBox, selectEl, todayIso, uid } from "../ui";

export async function renderNewCase(root: HTMLElement) {
  const [firm, lawyers, cases, profile, invite] = await Promise.all([getFirm(), listLawyers(), listCases(), getProfile(), inviteState(true)]);
  const number = nextCaseNumber(firm.caseNumberPattern, cases.map((c) => c.caseNumber));
  const title = input("title", "", { required: "", maxlength: "200", placeholder: "np. Kowalski / APM Orkana" });
  const caseNumber = input("caseNumber", number, { maxlength: "64" });
  const lawyer = selectEl("lawyer", [["", "— brak —"], ...lawyers.filter((l) => l.active).map((l) => [l.id, `${l.fullName}, ${l.title}`] as [string, string])], profile.lawyerId ?? "");
  const asOf = input("asOf", todayIso(), { type: "date" });
  const files = input("files", "", { type: "file", accept: "application/pdf", multiple: "" });
  const error = h("p", { class: "alert error", hidden: "" });

  const start = button("Odczytaj i zanonimizuj", () => void run());
  const exhausted = invite.ok && invite.invite && invite.invite.used >= invite.invite.limit;
  const access = !invite.ok
    ? h("p", { class: "alert error" }, ERRORS[invite.code] ?? `Brak dostępu do serwera analizy (${invite.code}).`)
    : exhausted ? h("p", { class: "alert error" }, ERRORS.invite_exhausted)
    : invite.invite ? h("p", { class: "alert info" }, h("strong", {}, `Zaproszenie: ${invite.invite.name}`), ` — ${inviteSummary(invite.invite)}. Analiza zakończona błędem nie zużywa limitu.`)
    : null;
  if (!invite.ok || exhausted) start.disabled = true;
  root.replaceChildren(h("section", { class: "card" },
    h("h1", {}, "Nowa sprawa"),
    access,
    h("div", { class: "alert info" },
      h("strong", {}, "Jak chronimy dane. "),
      "Skany są odczytywane i anonimizowane na tym komputerze. Zanim cokolwiek zostanie wysłane, zobaczysz oryginał obok tekstu do wysłania. ",
      "Do serwera analizy trafia wyłącznie zatwierdzony tekst bez danych osobowych. Sprawa zapisuje się zaszyfrowana tylko na tym komputerze."),
    h("div", { class: "stack" },
      labeled("Nazwa sprawy", title),
      h("div", { class: "row" }, labeled("Sygnatura", caseNumber), labeled("Prawnik prowadzący", lawyer)),
      labeled("Wyliczenie na dzień", asOf),
      labeled("Dokumenty PDF (umowa deweloperska, aneksy, protokół odbioru, akt przeniesienia własności)", files),
      h("div", { class: "row" }, start), error,
      h("p", { class: "muted small" }, "Skany: OCR kilka sekund na stronę. Pierwsze uruchomienie pobiera model języka polskiego (ok. 3 MB)."))));

  async function run() {
    error.hidden = true;
    const picked = [...(files.files ?? [])];
    if (!picked.length) { error.textContent = "Wybierz pliki PDF."; error.hidden = false; return; }
    const progress = progressBox();
    root.replaceChildren(progress.el);
    const docs: (CaseDoc & { bytes: Uint8Array<ArrayBuffer> })[] = [];
    try {
      for (const [i, f] of picked.entries()) {
        const buf = await f.arrayBuffer();
        const text = await readPdfText(buf, (page, pages, ocr) => progress.set(
          "Odczyt dokumentów na tym komputerze",
          `Dokument ${i + 1} z ${picked.length} (${f.name}) — ${ocr ? "OCR skanu" : "odczyt"}: strona ${page} z ${pages}`,
          5 + ((i + (page - 1) / pages) / picked.length) * 85));
        docs.push({ id: `doc_${i + 1}`, name: f.name, ocrPages: text.ocrPages, pages: text.pages, anon: [], bytes: new Uint8Array(buf) });
      }
      progress.set("Anonimizacja", "Zastępowanie danych osobowych znacznikami…", 95);
      await new Promise((r) => setTimeout(r, 30));
      const result = anonymizePages(new Map(docs.map((d) => [d.id, d.pages])));
      for (const d of docs) d.anon = result.pages.get(d.id)!;
      approval(docs, result.anonymizer, result.persons);
    } catch (e) {
      await renderNewCase(root);
      const box = root.querySelector<HTMLElement>(".alert.error")!;
      box.textContent = `Nie udało się odczytać plików: ${e instanceof Error ? e.message : e}`;
      box.hidden = false;
    }
  }

  function approval(docs: (CaseDoc & { bytes: Uint8Array<ArrayBuffer> })[], anonymizer: Anonymizer, persons: Person[]) {
    const unique = new Map<string, { label: string; original: string }>();
    for (const r of anonymizer.replacements) if (!unique.has(r.token)) unique.set(r.token, r);
    const tbody = h("tbody");
    for (const [token, r] of unique) {
      tbody.append(h("tr", {}, h("td", {}, r.original), h("td", {}, LABEL_NAMES[r.label] ?? r.label), h("td", {}, h("code", {}, token))));
    }
    // Capitalized words left in the komparycja: highlighted for the lawyer (a hint, the text is not changed).
    const suspects = [...new Set(docs.flatMap((d) => suspiciousWords(d.anon)))];
    const marked = (text: string): (Node | string)[] => {
      if (!suspects.length) return [text];
      const re = new RegExp(suspects.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "gu");
      const out: (Node | string)[] = [];
      let pos = 0;
      for (const m of text.matchAll(re)) {
        out.push(text.slice(pos, m.index), h("mark", {}, m[0]));
        pos = m.index! + m[0].length;
      }
      out.push(text.slice(pos));
      return out;
    };
    const suspectBox = suspects.length
      ? h("div", { class: "alert warn" }, h("strong", {}, "Sprawdź te słowa. "),
        "W komparycji po anonimizacji zostały wyrazy pisane wielką literą. Jeśli któryś to imię lub nazwisko, nie wysyłaj — anuluj i zgłoś nam przypadek. W podglądzie są zaznaczone na żółto: ",
        ...suspects.flatMap((w, i) => [i ? ", " : "", h("mark", {}, w)]))
      : null;
    const previews = docs.map((d) => {
      const details = h("details", {}, h("summary", {}, `Podgląd: oryginał i tekst do wysłania — ${d.name} (${d.anon.length} str.${d.ocrPages.length ? `, OCR: ${d.ocrPages.length}` : ""})`));
      d.anon.forEach((p, i) => details.append(h("div", { class: "compare" },
        h("div", {}, h("div", { class: "muted small" }, `strona ${i + 1} — oryginał (zostaje u Ciebie)`), h("pre", { class: "page" }, d.pages[i])),
        h("div", {}, h("div", { class: "muted small" }, `strona ${i + 1} — po anonimizacji (wysyłane)`), h("pre", { class: "page sent" }, ...marked(p))))));
      return details;
    });
    const check = h("input", { type: "checkbox" }) as HTMLInputElement;
    const approve = button("Zatwierdzam i wysyłam do analizy", () => {
      if (!check.checked) { check.focus(); return; }
      void analyze(docs, anonymizer, persons, unique);
    });
    root.replaceChildren(h("section", { class: "card" },
      h("h2", {}, "Sprawdź, co zostanie wysłane"),
      h("p", {}, `Zastąpiono ${unique.size} danych. Dane osobowe zostają na tym komputerze — do serwera trafi wyłącznie tekst z prawej kolumny podglądu.`),
      suspectBox ?? "",
      h("table", { class: "grid" }, h("thead", {}, h("tr", {}, h("th", {}, "Oryginał (zostaje u Ciebie)"), h("th", {}, "Rodzaj"), h("th", {}, "Po anonimizacji (wysyłane)"))), tbody),
      ...previews,
      h("label", { class: "row" }, check, " Podgląd został przejrzany — w tekście do wysłania nie ma danych osobowych."),
      h("div", { class: "row" }, approve, button("Anuluj", () => void renderNewCase(root), "secondary"))));
  }

  async function analyze(docs: (CaseDoc & { bytes: Uint8Array<ArrayBuffer> })[], anonymizer: Anonymizer, persons: Person[],
                         unique: Map<string, { label: string; original: string }>) {
    const record: CaseRecord = {
      id: uid(), title: title.value.trim() || docs[0].name, caseNumber: caseNumber.value.trim(), lawyerId: lawyer.value,
      createdAt: new Date().toISOString(), asOf: asOf.value || todayIso(), status: "analyzing",
      documents: docs.map(({ bytes: _bytes, ...d }) => d),
      mapping: [...anonymizer.mapping], persons,
      replacements: [...unique].map(([token, r]) => ({ token, label: r.label, original: r.original })),
      analysis: null, corrections: [],
    };
    await saveCase(record);
    for (const d of docs) await saveCasePdf(record.id, d.id, d.bytes);
    await runAnalysis(root, record);
  }
}

/** Send the stored anonymized text for analysis and save the result (also used by "Spróbuj ponownie"). */
export async function runAnalysis(root: HTMLElement, record: CaseRecord) {
  const progress = progressBox();
  root.replaceChildren(progress.el);
  const started = Date.now();
  let label = "Wysyłanie zatwierdzonego tekstu";
  let pct = 5;
  const tick = setInterval(() => progress.set("Analiza", `${label} — ${Math.round((Date.now() - started) / 1000)} s`, pct), 1000);
  progress.set("Analiza", label, pct);
  try {
    const result = await analyzeText(record.documents.map((d) => ({ id: d.id, pages: d.anon })), (l, p) => { label = l; pct = p; });
    record.analysis = result as CaseRecord["analysis"];
    record.status = "ready";
    record.errorCode = undefined;
  } catch (e) {
    record.status = "error";
    record.errorCode = e instanceof ApiError ? e.message : "internal_error";
  } finally {
    clearInterval(tick);
  }
  await saveCase(record);
  location.hash = `#/case/${record.id}`;
}

export const errorText = (code?: string) => ERRORS[code ?? ""] ?? code ?? "Nieznany błąd.";
