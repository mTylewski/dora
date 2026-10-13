// Lawyer corrections in the browser - port of app/corrections.py (parsing, applying, quote mismatch).
import { type Extraction, iterFields } from "./schema";

export class CorrectionError extends Error {}

export type Kind = "text" | "date" | "decimal" | "amount" | "basis" | "cap" | "events" | "bool";

export const EDITABLE: Record<string, Kind> = {
  developer_name: "text",
  agreement_reference: "text",
  agreement_date: "date",
  price_gross: "amount",
  handover_deadline: "date",
  transfer_deadline: "date",
  penalty_basis: "basis",
  penalty_rate: "decimal",
  penalty_cap: "cap",
  penalty_events: "events",
  exclusive_penalty_clause: "bool",
  waiver_of_claims: "bool",
  actual_handover_date: "date",
  actual_transfer_date: "date",
};

export function kindOf(path: string): Kind | null {
  if (path in EDITABLE) return EDITABLE[path];
  if (/^annex_deadlines\[\d+\]$/.test(path)) return "date";
  return null;
}

/** "1.080.000,00" / "1 080 000,00" / "1080000.50" / "0,0001" -> plain decimal string. */
export function normalizeNumber(raw: string): string {
  let s = raw.replace(/[  ]/g, "").replace(/zł|PLN|%/gi, "").trim();
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else if ((s.match(/\./g) ?? []).length > 1) s = s.replace(/\./g, "");
  return s;
}

export function parseNumber(raw: string): number {
  const s = normalizeNumber(raw);
  if (!/^-?\d+(\.\d+)?$/.test(s)) throw new CorrectionError(`nieprawidłowa liczba: ${raw}`);
  return Number(s);
}

export function parseDate(raw: string): string {
  const s = raw.trim();
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) {
    const pl = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(s);
    if (pl) m = [s, pl[3], pl[2].padStart(2, "0"), pl[1].padStart(2, "0")] as unknown as RegExpExecArray;
  }
  if (!m) throw new CorrectionError(`nieprawidłowa data: ${raw} (użyj DD.MM.RRRR)`);
  const iso = `${m[1]}-${m[2]}-${m[3]}`;
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== iso) throw new CorrectionError(`nieprawidłowa data: ${raw}`);
  return iso;
}

/** Value entered by the lawyer -> JSON value of the field (null for "brak"/empty). */
export function parseValue(kind: Kind, raw: string): unknown {
  const s = raw.trim();
  if (s === "" || s.toLowerCase() === "brak") return null;
  switch (kind) {
    case "text": return s;
    case "date": return parseDate(s);
    case "decimal":
    case "amount": return parseNumber(s);
    case "basis": return s;
    case "bool":
      if (["tak", "true", "1"].includes(s.toLowerCase())) return true;
      if (["nie", "false", "0"].includes(s.toLowerCase())) return false;
      throw new CorrectionError("wybierz: tak / nie / brak");
    case "cap":
      if (s.endsWith("%")) return { type: "percent", value: parseNumber(s.slice(0, -1)) / 100 };
      return { type: "amount", value: parseNumber(s) };
    case "events": return s.split(",").map((e) => e.trim()).filter(Boolean);
  }
}

export interface Correction { value: unknown; confirmed: boolean }

/** New Extraction with corrections applied; corrected fields are no longer marked for review. */
export function applyCorrections(original: Extraction, corrections: Map<string, Correction>): Extraction {
  const ex = structuredClone(original) as Extraction;
  for (const [path, c] of corrections) {
    const annex = /^annex_deadlines\[(\d+)\]$/.exec(path);
    if (annex) {
      const item = ex.annex_deadlines[Number(annex[1])];
      if (item?.value) item.value = { ...item.value, date: c.value as string };
      if (item) item.confidence = "high";
      continue;
    }
    const field = (ex as unknown as Record<string, { value: unknown; confidence: string }>)[path];
    if (field) {
      field.value = c.value;
      field.confidence = "high";
    }
  }
  return ex;
}

export function valuesEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

const NUMBER_IN_TEXT = /\d{1,3}(?:[ . ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?/g;

export function numbersInQuote(quote: string | null): number[] {
  return (quote?.match(NUMBER_IN_TEXT) ?? []).map((m) => Number(normalizeNumber(m))).filter((n) => !Number.isNaN(n));
}

const close = (a: number, b: number) => Math.abs(a - b) < 1e-9 * Math.max(1, Math.abs(a));

/** Does a numeric value appear in its quote? null when it cannot be checked. */
export function valueMatchesQuote(path: string, value: unknown, quote: string | null): boolean | null {
  if (value === null || value === undefined || !quote) return null;
  const numbers = numbersInQuote(quote);
  if (!numbers.length) return null;
  if (path === "price_gross") return numbers.some((n) => close(n, Number(value)));
  if (path === "penalty_rate") return numbers.some((n) => close(n, Number(value)) || close(n, Number(value) * 100));
  if (path === "penalty_cap" && typeof value === "object") {
    const c = value as { type: string; value: number };
    return numbers.some((n) => close(n, c.value) || (c.type === "percent" && close(n, c.value * 100)));
  }
  return null;
}

/** The single amount (>= 1000) in a quote, or null when there is none or several. */
export function amountInQuote(quote: string | null): number | null {
  const amounts = [...new Set(numbersInQuote(quote).filter((n) => n >= 1000))];
  return amounts.length === 1 ? amounts[0] : null;
}

/** Edit-box text for a value (Polish formats). */
export function editValue(path: string, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (path.startsWith("annex_deadlines")) return isoToPl((value as { date: string }).date);
  if (path === "price_gross") return groupAmount(Number(value));
  if (path === "penalty_cap") {
    const c = value as { type: string; value: number };
    return c.type === "percent" ? `${+(c.value * 100).toFixed(6)}%` : groupAmount(c.value);
  }
  if (path === "penalty_events") return (value as string[]).join(", ");
  if (typeof value === "boolean") return value ? "tak" : "nie";
  if (/_date$|_deadline$/.test(path)) return isoToPl(value as string);
  return String(value);
}

export function isoToPl(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
}

export function groupAmount(n: number): string {
  const [int, frac = ""] = n.toFixed(2).split(".");
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + "," + frac;
}

/** Thousands separators while typing (same behaviour as web/static/app.js in the MVP). */
export function formatAmountInput(raw: string): string {
  const cleaned = raw.replace(/[^\d,.]/g, "");
  const group = (i: string) => i.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const comma = cleaned.indexOf(",");
  if (comma !== -1) {
    return group(cleaned.slice(0, comma).replace(/\./g, "")) + "," + cleaned.slice(comma + 1).replace(/[.,]/g, "").slice(0, 2);
  }
  const lastDot = cleaned.lastIndexOf(".");
  if (lastDot !== -1 && cleaned.length - lastDot - 1 <= 2) {
    return group(cleaned.slice(0, lastDot).replace(/\./g, "")) + "." + cleaned.slice(lastDot + 1);
  }
  return group(cleaned.replace(/\./g, ""));
}

export function editablePaths(ex: Extraction): string[] {
  return iterFields(ex).map(([p]) => p).filter((p) => kindOf(p) !== null);
}
