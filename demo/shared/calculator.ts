// Deterministic delay-penalty calculator - TypeScript port of calculator/ (Python).
// Money is integer grosze in BigInt; rates are exact decimals (BigInt numerator / 10^scale).
// No floating point arithmetic on money. Rounding: half up, once per final amount.

export type Basis = "percent_of_price_per_day" | "fixed_per_day" | "statutory_interest" | "other";
export type Event = "handover_delay" | "transfer_delay";

export const EVENT_LABELS: Record<Event, string> = {
  handover_delay: "opóźnienie w wydaniu lokalu",
  transfer_delay: "opóźnienie w zawarciu umowy przenoszącej własność",
};

export class CalculationError extends Error {}

// --- exact decimals ----------------------------------------------------------------

export interface Dec { num: bigint; scale: number } // value = num / 10^scale

export function dec(value: number | string): Dec {
  let s = typeof value === "number" ? String(value) : value.trim();
  if (!/^-?\d+(\.\d+)?(e[+-]?\d+)?$/i.test(s)) throw new CalculationError(`not a number: ${s}`);
  let exp = 0;
  const e = s.toLowerCase().indexOf("e");
  if (e !== -1) {
    exp = parseInt(s.slice(e + 1), 10);
    s = s.slice(0, e);
  }
  const [int, frac = ""] = s.split(".");
  let num = BigInt(int + frac);
  let scale = frac.length - exp;
  if (scale < 0) {
    num *= 10n ** BigInt(-scale);
    scale = 0;
  }
  return { num, scale };
}

const pow10 = (n: number) => 10n ** BigInt(n);

/** Round num/den (both non-negative) half up to an integer. */
export function divHalfUp(num: bigint, den: bigint): bigint {
  if (num < 0n || den <= 0n) throw new CalculationError("negative amount");
  return (2n * num + den) / (2n * den);
}

export function decToString(d: Dec): string {
  const neg = d.num < 0n;
  const digits = (neg ? -d.num : d.num).toString().padStart(d.scale + 1, "0");
  let out = d.scale ? `${digits.slice(0, -d.scale)}.${digits.slice(-d.scale)}` : digits;
  if (out.includes(".")) out = out.replace(/0+$/, "").replace(/\.$/, "");
  return (neg ? "-" : "") + out;
}

export function fmtPercent(fraction: Dec): string {
  const percent: Dec = fraction.scale >= 2
    ? { num: fraction.num, scale: fraction.scale - 2 }
    : { num: fraction.num * pow10(2 - fraction.scale), scale: 0 };
  return decToString(percent).replace(".", ",") + "%";
}

export function plnToGrosze(pln: Dec): bigint {
  return divHalfUp(pln.num * 100n, pow10(pln.scale));
}

export function formatPln(grosze: bigint): string {
  const neg = grosze < 0n;
  const abs = neg ? -grosze : grosze;
  const zl = (abs / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const gr = (abs % 100n).toString().padStart(2, "0");
  return `${neg ? "-" : ""}${zl},${gr} zł`;
}

// --- dates (ISO strings, UTC day numbers) ---------------------------------------------

const DAY = 86_400_000;
export const dayNum = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / DAY;
};
export const isoOf = (n: number) => new Date(n * DAY).toISOString().slice(0, 10);
export const fmtDate = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

// --- model ------------------------------------------------------------------------------

export interface CalcConfig { includeActualDate: boolean; interestYearDays: number; verified: boolean }
export interface Amendment { newDeadline: string; annexNo: number | null }
export interface EffectiveDeadline { deadline: string; source: "contract" | "annex"; annexNo: number | null }
export interface Cap { type: "percent" | "amount"; value: Dec }
export interface RatePeriod { from: string; to: string | null; rate: Dec; source: string; verified: boolean }
export interface Terms { basis: Basis; priceGrosze: bigint; rate: Dec | null; cap: Cap | null; interestTable: RatePeriod[] | null }
export interface Step { label: string; formula: string; result: string }
export interface PenaltyResult {
  event: Event;
  effectiveDeadline: EffectiveDeadline;
  endDate: string;
  ongoing: boolean;
  days: number;
  uncappedGrosze: bigint | null;
  capGrosze: bigint | null;
  cappedGrosze: bigint | null;
  capReached: boolean;
  steps: Step[];
  warnings: string[];
}

export function describeDeadline(e: EffectiveDeadline): string {
  if (e.source === "contract") return "umowa";
  return e.annexNo !== null ? `aneks nr ${e.annexNo}` : "aneks (bez numeru)";
}

export function effectiveDeadline(contract: string | null, amendments: Amendment[]): EffectiveDeadline {
  if (amendments.length) {
    const ordered = [...amendments];
    if (ordered.every((a) => a.annexNo !== null)) ordered.sort((a, b) => a.annexNo! - b.annexNo!);
    const last = ordered[ordered.length - 1];
    return { deadline: last.newDeadline, source: "annex", annexNo: last.annexNo };
  }
  if (contract === null) throw new CalculationError("brak terminu w umowie i w aneksach");
  return { deadline: contract, source: "contract", annexNo: null };
}

export function delayPeriod(deadline: string, end: string, cfg: CalcConfig) {
  const first = dayNum(deadline) + 1;
  const last = cfg.includeActualDate ? dayNum(end) : dayNum(end) - 1;
  const days = last - first + 1;
  if (days <= 0) return { first: isoOf(first), last: isoOf(first - 1), days: 0 };
  return { first: isoOf(first), last: isoOf(last), days };
}

function rateFor(table: RatePeriod[], day: number): RatePeriod {
  const p = table.find((r) => dayNum(r.from) <= day && (r.to === null || day <= dayNum(r.to)));
  if (!p) throw new CalculationError(`brak stawki odsetek dla ${isoOf(day)}`);
  return p;
}

export function statutoryInterest(principal: bigint, first: string, last: string, table: RatePeriod[], cfg: CalcConfig) {
  const segments: { start: string; end: string; days: number; rate: Dec; source: string; verified: boolean }[] = [];
  if (dayNum(last) < dayNum(first)) return { grosze: 0n, segments, allVerified: table.every((p) => p.verified) };
  // Sum exact fractions over a common denominator, round once.
  const maxScale = Math.max(0, ...table.map((p) => p.rate.scale));
  let numerator = 0n;
  let day = dayNum(first);
  const end = dayNum(last);
  while (day <= end) {
    const p = rateFor(table, day);
    const segEnd = p.to === null ? end : Math.min(dayNum(p.to), end);
    const days = segEnd - day + 1;
    segments.push({ start: isoOf(day), end: isoOf(segEnd), days, rate: p.rate, source: p.source, verified: p.verified });
    numerator += principal * p.rate.num * pow10(maxScale - p.rate.scale) * BigInt(days);
    day = segEnd + 1;
  }
  const grosze = divHalfUp(numerator, pow10(maxScale) * BigInt(cfg.interestYearDays));
  return { grosze, segments, allVerified: segments.every((s) => s.verified) };
}

export function computePenalty(
  event: Event, contractDeadline: string | null, amendments: Amendment[], actual: string | null,
  asOf: string, terms: Terms, cfg: CalcConfig,
): PenaltyResult {
  const eff = effectiveDeadline(contractDeadline, amendments);
  const ongoing = actual === null;
  const end = actual ?? asOf;
  const { first, last, days } = delayPeriod(eff.deadline, end, cfg);
  const r: PenaltyResult = {
    event, effectiveDeadline: eff, endDate: end, ongoing, days,
    uncappedGrosze: null, capGrosze: null, cappedGrosze: null, capReached: false, steps: [], warnings: [],
  };
  r.steps.push({ label: "Termin efektywny", formula: `termin z dokumentu: ${describeDeadline(eff)}`, result: fmtDate(eff.deadline) });
  const endLabel = ongoing ? `stan na dzień ${fmtDate(end)} (opóźnienie trwa)` : `data faktyczna ${fmtDate(end)}`;
  const inclusion = cfg.includeActualDate ? "wliczając" : "nie wliczając";
  r.steps.push({ label: "Dni opóźnienia", formula: `od ${fmtDate(first)} do ${endLabel}, ${inclusion} dnia końcowego`, result: String(days) });
  if (ongoing) r.warnings.push(`Brak daty faktycznej — opóźnienie liczone na dzień ${fmtDate(asOf)}.`);
  if (!cfg.verified) r.warnings.push("Sposób liczenia dni nie został potwierdzony przez prawnika (config/calculator.yaml).");

  if (terms.basis === "other") {
    r.warnings.push("Nietypowy sposób naliczania kary — wymaga ręcznego wyliczenia.");
    return r;
  }
  let uncapped: bigint;
  if (terms.basis === "percent_of_price_per_day") {
    const rate = requireRate(terms);
    uncapped = divHalfUp(terms.priceGrosze * rate.num * BigInt(days), pow10(rate.scale));
    r.steps.push({ label: "Kara umowna", formula: `${formatPln(terms.priceGrosze)} × ${fmtPercent(rate)} × ${days} dni`, result: formatPln(uncapped) });
  } else if (terms.basis === "fixed_per_day") {
    const rate = requireRate(terms);
    uncapped = divHalfUp(rate.num * 100n * BigInt(days), pow10(rate.scale));
    r.steps.push({ label: "Kara umowna", formula: `${formatPln(plnToGrosze(rate))} × ${days} dni`, result: formatPln(uncapped) });
  } else {
    if (!terms.interestTable) throw new CalculationError("brak tabeli odsetek ustawowych");
    const res = statutoryInterest(terms.priceGrosze, first, last, terms.interestTable, cfg);
    uncapped = res.grosze;
    for (const s of res.segments) {
      r.steps.push({
        label: `Odsetki ${fmtDate(s.start)}–${fmtDate(s.end)}`,
        formula: `${formatPln(terms.priceGrosze)} × ${fmtPercent(s.rate)} × ${s.days}/${cfg.interestYearDays}`,
        result: s.source || "brak źródła stawki",
      });
    }
    r.steps.push({ label: "Suma odsetek", formula: "suma okresów, zaokrąglenie do grosza", result: formatPln(uncapped) });
    if (!res.allVerified) r.warnings.push("Użyte stawki odsetek nie są oznaczone jako zweryfikowane.");
  }
  r.uncappedGrosze = uncapped;
  r.cappedGrosze = uncapped;
  if (terms.cap) {
    const capG = terms.cap.type === "percent"
      ? divHalfUp(terms.priceGrosze * terms.cap.value.num, pow10(terms.cap.value.scale))
      : plnToGrosze(terms.cap.value);
    r.capGrosze = capG;
    r.cappedGrosze = uncapped < capG ? uncapped : capG;
    r.capReached = uncapped > capG;
    r.steps.push({
      label: "Limit kary",
      formula: terms.cap.type === "percent" ? `${formatPln(terms.priceGrosze)} × ${fmtPercent(terms.cap.value)}` : "kwota wskazana w umowie",
      result: formatPln(capG),
    });
    r.steps.push({ label: "Kara po zastosowaniu limitu", formula: `min(${formatPln(uncapped)}, ${formatPln(capG)})`, result: formatPln(r.cappedGrosze) });
    r.warnings.push("Umowa ogranicza wysokość kary — klauzula potencjalnie abuzywna, do oceny prawnika.");
  }
  return r;
}

function requireRate(terms: Terms): Dec {
  if (!terms.rate) throw new CalculationError("brak stawki kary");
  return terms.rate;
}

// --- case level ------------------------------------------------------------------------

export interface CaseInput {
  terms: Terms;
  penaltyEvents: Event[];
  asOf: string;
  handoverDeadline: string | null;
  transferDeadline: string | null;
  handoverAmendments: Amendment[];
  transferAmendments: Amendment[];
  actualHandoverDate: string | null;
  actualTransferDate: string | null;
}

export interface TimelineEntry { date: string; label: string; kind: "deadline" | "annex" | "actual" | "as_of" }

export function calculateCase(c: CaseInput, cfg: CalcConfig) {
  const penalties: PenaltyResult[] = [];
  const skipped: string[] = [];
  const plan: [Event, string | null, Amendment[], string | null][] = [
    ["handover_delay", c.handoverDeadline, c.handoverAmendments, c.actualHandoverDate],
    ["transfer_delay", c.transferDeadline, c.transferAmendments, c.actualTransferDate],
  ];
  for (const [event, deadline, amendments, actual] of plan) {
    if (!c.penaltyEvents.includes(event)) continue;
    try {
      penalties.push(computePenalty(event, deadline, amendments, actual, c.asOf, c.terms, cfg));
    } catch (e) {
      if (!(e instanceof CalculationError)) throw e;
      skipped.push(`${EVENT_LABELS[event]}: ${e.message}`);
    }
  }
  const sum = (key: "uncappedGrosze" | "cappedGrosze") => penalties.reduce((a, p) => a + (p[key] ?? 0n), 0n);
  return { penalties, skipped, timeline: buildTimeline(c), totalUncapped: sum("uncappedGrosze"), totalCapped: sum("cappedGrosze") };
}

export function buildTimeline(c: CaseInput): TimelineEntry[] {
  const e: TimelineEntry[] = [];
  if (c.handoverDeadline) e.push({ date: c.handoverDeadline, label: "Termin wydania lokalu (umowa)", kind: "deadline" });
  if (c.transferDeadline) e.push({ date: c.transferDeadline, label: "Termin umowy przenoszącej (umowa)", kind: "deadline" });
  for (const [what, list] of [["wydania lokalu", c.handoverAmendments], ["umowy przenoszącej", c.transferAmendments]] as const) {
    for (const a of list) {
      e.push({ date: a.newDeadline, label: `Termin ${what} (aneks ${a.annexNo !== null ? `nr ${a.annexNo}` : "bez numeru"})`, kind: "annex" });
    }
  }
  if (c.actualHandoverDate) e.push({ date: c.actualHandoverDate, label: "Faktyczne wydanie lokalu", kind: "actual" });
  if (c.actualTransferDate) e.push({ date: c.actualTransferDate, label: "Zawarcie umowy przenoszącej", kind: "actual" });
  e.push({ date: c.asOf, label: "Data wyliczenia", kind: "as_of" });
  return e.sort((a, b) => a.date.localeCompare(b.date));
}
