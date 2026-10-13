// Firm settings and lawyers (stored encrypted on this computer).
import { type Lawyer, getFirm, getProfile, listCases, listLawyers, nextCaseNumber, saveFirm, saveLawyer, saveProfile } from "../store";
import { LAWYER_TITLES, button, h, input, labeled, selectEl, uid } from "../ui";

export async function renderFirm(root: HTMLElement) {
  const [firm, lawyers, profile, cases] = await Promise.all([getFirm(), listLawyers(), getProfile(), listCases()]);
  const saved = h("p", { class: "alert info", hidden: "" }, "Zapisano.");

  const f = {
    name: input("name", firm.name), address: input("address", firm.address), city: input("city", firm.city),
    bankAccount: input("bankAccount", firm.bankAccount),
    days: input("days", String(firm.paymentDeadlineDays), { type: "number", min: "1" }),
    pattern: input("pattern", firm.caseNumberPattern),
    legal: h("textarea", { name: "legal", rows: "3" }, firm.legalBasis) as HTMLTextAreaElement,
  };
  const example = h("strong", {}, nextCaseNumber(firm.caseNumberPattern, cases.map((c) => c.caseNumber)));
  f.pattern.addEventListener("input", () => { example.textContent = nextCaseNumber(f.pattern.value, cases.map((c) => c.caseNumber)); });

  const firmCard = h("section", { class: "card" }, h("h2", {}, "Dane kancelarii"),
    h("p", { class: "muted small" }, "Używane w pismach (nagłówek, miejscowość, rachunek) i przy zakładaniu spraw."),
    h("div", { class: "stack" },
      labeled("Nazwa kancelarii", f.name), labeled("Adres", f.address),
      h("div", { class: "row" }, labeled("Miejscowość (w nagłówku pisma)", f.city), labeled("Termin zapłaty w wezwaniach (dni)", f.days)),
      labeled("Domyślny rachunek do zapłaty", f.bankAccount),
      labeled("Wzór sygnatury sprawy", f.pattern),
      h("p", { class: "muted small" }, h("code", {}, "{rok}"), " — bieżący rok, ", h("code", {}, "{nr}"), " — kolejny numer w roku. Następna sygnatura: ", example),
      labeled("Podstawa prawna (tekst domyślny w pismach, do zatwierdzenia przez prawnika)", f.legal),
      button("Zapisz", async () => {
        await saveFirm({
          name: f.name.value.trim(), address: f.address.value.trim(), city: f.city.value.trim(),
          bankAccount: f.bankAccount.value.trim(), paymentDeadlineDays: Math.max(1, Number(f.days.value) || 14),
          caseNumberPattern: f.pattern.value.trim() || "KAN/{rok}/{nr}", legalBasis: f.legal.value.trim(),
        });
        saved.hidden = false;
      })));

  const tbody = h("tbody");
  const rows = [...lawyers, { id: "", fullName: "", title: "adwokat", registryNo: "", active: true } as Lawyer];
  for (const l of rows) {
    const name = input("fullName", l.fullName, { placeholder: "imię i nazwisko" });
    const title = selectEl("title", LAWYER_TITLES.map((t) => [t, t] as [string, string]), l.title);
    const registry = input("registryNo", l.registryNo, { placeholder: "np. WAW/Adw/1234" });
    const active = selectEl("active", [["yes", "tak"], ["no", "nie"]], l.active ? "yes" : "no");
    // The first lawyer added on a fresh account is preselected as "me".
    const isMe = l.id ? l.id === profile.lawyerId : !lawyers.length && !profile.lawyerId;
    const me = h("input", { type: "radio", name: "me", ...(isMe ? { checked: "" } : {}) }) as HTMLInputElement;
    tbody.append(h("tr", {},
      h("td", {}, name), h("td", {}, title), h("td", {}, registry), h("td", {}, l.id ? active : "nowy"),
      h("td", { title: "To ja — domyślny prawnik w moich sprawach" }, me),
      h("td", {}, button(l.id ? "Zapisz" : "Dodaj", async () => {
        if (!name.value.trim()) { name.focus(); return; }
        const lawyer: Lawyer = { id: l.id || uid(), fullName: name.value.trim(), title: title.value, registryNo: registry.value.trim(), active: l.id ? active.value === "yes" : true };
        await saveLawyer(lawyer);
        if (me.checked) await saveProfile({ ...profile, lawyerId: lawyer.id });
        await renderFirm(root);
      }, l.id ? "secondary" : ""))));
  }
  const lawyersCard = h("section", { class: "card" }, h("h2", {}, "Prawnicy"),
    h("p", { class: "muted small" }, "Prawnik prowadzący sprawę i podpisujący pismo. Zaznacz „to ja”, żeby był wybierany domyślnie w nowych sprawach."),
    h("table", { class: "grid" }, h("thead", {}, h("tr", {}, ...["Imię i nazwisko", "Tytuł", "Nr wpisu", "Aktywny", "To ja", ""].map((t) => h("th", {}, t)))), tbody));

  root.replaceChildren(h("h1", {}, "Kancelaria"), saved, firmCard, lawyersCard);
}
