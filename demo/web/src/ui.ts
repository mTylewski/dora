// Small DOM helpers and labels shared by the pages. Model output is rendered only through textContent.

export type Child = Node | string | null | undefined | false;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}, ...children: Child[]) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const c of children) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

export const $ = <T extends HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector<T>(sel)!;

export function button(text: string, onClick: () => void, cls = ""): HTMLButtonElement {
  const b = h("button", { type: "button", ...(cls ? { class: cls } : {}) }, text);
  b.addEventListener("click", onClick);
  return b;
}

export function input(name: string, value = "", attrs: Record<string, string> = {}): HTMLInputElement {
  return h("input", { name, value, ...attrs });
}

export function labeled(label: string, control: HTMLElement): HTMLLabelElement {
  return h("label", {}, label, control);
}

export function selectEl(name: string, options: [string, string][], current: string): HTMLSelectElement {
  const el = h("select", { name });
  for (const [value, text] of options) {
    const opt = h("option", { value }, text);
    if (value === current) opt.setAttribute("selected", "");
    el.append(opt);
  }
  return el;
}

export function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const todayIso = () => new Date().toISOString().slice(0, 10);
export const uid = () => crypto.randomUUID().replace(/-/g, "").slice(0, 16);
export const safeFileName = (s: string) => s.replace(/[^\p{L}\p{N}]+/gu, "_").replace(/^_+|_+$/g, "").slice(0, 80);

/** Spinner + progress bar + text, updated in place. */
export function progressBox() {
  const title = h("strong", {});
  const bar = h("progress", { class: "progress", max: "100", value: "2" }) as HTMLProgressElement;
  const text = h("p", {});
  const el = h("section", { class: "card progress-card" }, h("div", { class: "row" }, h("span", { class: "spinner", "aria-hidden": "true" }), title), bar, text);
  return {
    el,
    set(t: string, msg: string, pct: number) {
      title.textContent = t;
      text.textContent = msg;
      bar.value = Math.max(2, Math.min(100, pct));
    },
  };
}

export const LABELS: Record<string, string> = {
  developer_name: "Deweloper", agreement_reference: "Numer aktu umowy (Rep. A)",
  agreement_date: "Data zawarcia umowy deweloperskiej",
  price_gross: "Cena brutto", handover_deadline: "Termin wydania lokalu", transfer_deadline: "Termin umowy przenoszącej",
  penalty_basis: "Sposób naliczania kary", penalty_rate: "Stawka kary", penalty_cap: "Limit kary", penalty_events: "Kara za",
  exclusive_penalty_clause: "Kara wyłączna", waiver_of_claims: "Zrzeczenie się roszczeń",
  actual_handover_date: "Faktyczne wydanie lokalu", actual_transfer_date: "Faktyczna umowa przenosząca",
};
export const ISSUES: Record<string, string> = {
  quote_missing: "brak cytatu", quote_not_found: "cytatu nie znaleziono w dokumencie", page_mismatch: "cytat jest na innej stronie",
  page_missing: "brak numeru strony", unknown_document: "nieznany dokument", low_confidence: "niska pewność",
  value_unresolved: "wartości nie da się ustalić z dokumentu",
};
export const BASIS: Record<string, string> = {
  percent_of_price_per_day: "% ceny za dzień", fixed_per_day: "stała kwota za dzień", statutory_interest: "odsetki ustawowe", other: "inny sposób",
};
export const EVENTS: Record<string, string> = { handover_delay: "opóźnienie wydania lokalu", transfer_delay: "opóźnienie umowy przenoszącej" };
export const DOC_TYPES: Record<string, string> = {
  development_agreement: "umowa deweloperska", annex: "aneks", handover_protocol: "protokół odbioru",
  transfer_deed: "akt przeniesienia własności", other: "inny dokument",
};
export const ROLE_LABELS: Record<string, string> = { buyer: "nabywca", seller: "sprzedający", representative: "pełnomocnik / przedstawiciel", notary: "notariusz" };
export const LABEL_NAMES: Record<string, string> = {
  OSOBA: "osoba", PESEL: "PESEL", NIP: "NIP", REGON: "REGON", DOWOD: "dowód osobisty", KW: "księga wieczysta",
  KONTO: "rachunek", EMAIL: "e-mail", TELEFON: "telefon", KOD: "kod pocztowy", ADRES: "adres", RODZICE: "imiona rodziców", URODZENIE: "data urodzenia", NAZWISKO: "nazwisko rodowe",
};
export const ERRORS: Record<string, string> = {
  too_large: "Dokumenty są zbyt obszerne.", refusal: "Usługa AI odmówiła przetworzenia dokumentów.",
  invalid_output: "Usługa AI zwróciła niepoprawne dane (po ponownej próbie).", rate_limited: "Limit zapytań — spróbuj za chwilę.",
  pii_detected: "Serwer wykrył w tekście dane osobowe (np. PESEL) i odrzucił go. Nic nie zostało przetworzone.",
  api_error: "Błąd usługi AI.", internal_error: "Błąd serwera.", no_result: "Serwer nie zwrócił wyniku.",
  invite_missing: "Brak zaproszenia. Otwórz DORA z linku w wiadomości z zaproszeniem.",
  invite_invalid: "Link z zaproszeniem jest nieprawidłowy. Otwórz go ponownie z wiadomości lub poproś o nowy.",
  invite_expired: "Zaproszenie wygasło. Napisz do nas, a przedłużymy dostęp.",
  invite_revoked: "Zaproszenie zostało wyłączone.",
  invite_exhausted: "Wykorzystano wszystkie analizy z zaproszenia. Napisz do nas, a zwiększymy limit.",
  invites_unavailable: "Serwer zaproszeń jest chwilowo niedostępny.", offline: "Brak połączenia z serwerem analizy.",
};
export const LAWYER_TITLES = ["adwokat", "radca prawny", "aplikant adwokacki", "aplikant radcowski"];

/** "pozostało 7 z 10 analiz · ważne do 05.11.2026" */
export function inviteSummary(inv: { limit: number; used: number; expiresAt: string }): string {
  const left = Math.max(0, inv.limit - inv.used);
  return `pozostało ${left} z ${inv.limit} analiz · ważne do ${new Date(inv.expiresAt).toLocaleDateString("pl-PL")}`;
}
