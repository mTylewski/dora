// Extraction -> calculator, and anonymous facts for the letter. Ports of pipeline/calculate.py and pipeline/letter.py.
import config from "./generated/config.json";
import {
  type Amendment, type CalcConfig, type Event, type PenaltyResult, type RatePeriod, type Terms,
  EVENT_LABELS, calculateCase, dec, fmtDate, fmtPercent, formatPln, plnToGrosze,
} from "./calculator";
import type { Extraction } from "./schema";

export const FIELD_LABELS: Record<string, string> = {
  agreement_date: "data zawarcia umowy",
  price_gross: "cena",
  handover_deadline: "termin wydania lokalu",
  transfer_deadline: "termin umowy przenoszącej",
  penalty_basis: "sposób naliczania kary",
  penalty_rate: "stawka kary",
  penalty_cap: "limit kary",
  penalty_events: "zdarzenia objęte karą",
  actual_handover_date: "data wydania lokalu",
  actual_transfer_date: "data umowy przenoszącej",
};

export const CALC_CONFIG: CalcConfig = {
  includeActualDate: config.calculator.include_actual_date,
  interestYearDays: config.calculator.interest_year_days,
  verified: config.calculator.verified,
};

type RawPeriod = { from: string; to: string | null; rate: string; source?: string; verified?: boolean };

export function rateTable(kind: string): RatePeriod[] {
  const periods = (config.statutory_interest as Record<string, RawPeriod[]>)[kind] ?? [];
  return periods.map((p) => ({ from: p.from, to: p.to, rate: dec(p.rate), source: p.source ?? "", verified: !!p.verified }));
}

/** Flag agreements concluded before the new development act (date from config, to be verified). */
export function regimeWarnings(ex: Extraction, boundary = config.calculator.new_act_from, verified = config.calculator.new_act_verified): string[] {
  if (!boundary) return [];
  const signed = ex.agreement_date.value;
  if (signed === null) return ["Nie ustalono daty zawarcia umowy deweloperskiej — sprawdź, której ustawy dotyczy umowa."];
  if (signed < boundary) {
    const note = verified ? "" : " (data graniczna niezweryfikowana w config/calculator.yaml)";
    return [`Umowa zawarta ${fmtDate(signed)}, przed ${fmtDate(boundary)} — sprawdź przepisy przejściowe ustawy deweloperskiej${note}.`];
  }
  return [];
}

export function calculateFromExtraction(ex: Extraction, asOf: string, needsReview: Set<string>, cfg = CALC_CONFIG) {
  const warnings: string[] = [];
  const blocking: string[] = [];
  const review = Object.entries(FIELD_LABELS).filter(([k]) => needsReview.has(k)).map(([, v]) => v);
  if (review.length) warnings.push(`Dane wejściowe do sprawdzenia przez prawnika: ${review.join(", ")}.`);
  warnings.push(...regimeWarnings(ex));
  if (ex.waiver_of_claims.value === true) {
    warnings.push("Dokumenty zawierają oświadczenie o zrzeczeniu się roszczeń — kwoty wyliczono, skuteczność zrzeczenia do oceny prawnika.");
  }
  if (ex.price_gross.value === null) blocking.push("Brak ceny lokalu.");
  if (ex.penalty_basis.value === null) blocking.push("Brak sposobu naliczania kary.");
  if (blocking.length) return { result: null, blocking, warnings };

  const basis = ex.penalty_basis.value!;
  let table: RatePeriod[] | null = null;
  if (basis === "statutory_interest") {
    table = rateTable(config.calculator.statutory_interest_kind);
    if (!table.length) {
      blocking.push("Tabela odsetek ustawowych jest pusta — uzupełnij config/statutory_interest.yaml.");
      return { result: null, blocking, warnings };
    }
  }
  const terms: Terms = {
    basis,
    priceGrosze: plnToGrosze(dec(ex.price_gross.value!)),
    rate: ex.penalty_rate.value !== null ? dec(ex.penalty_rate.value) : null,
    cap: ex.penalty_cap.value ? { type: ex.penalty_cap.value.type, value: dec(ex.penalty_cap.value.value) } : null,
    interestTable: table,
  };
  let events: Event[] = ex.penalty_events.value ?? [];
  if (!events.length) {
    events = ["handover_delay", "transfer_delay"];
    warnings.push("Dokument nie wskazuje wprost, za jakie opóźnienie należy się kara — wyliczono dla obu zdarzeń, do oceny prawnika.");
  }
  const amendments = (fieldName: string): Amendment[] =>
    ex.annex_deadlines
      .filter((f) => f.value !== null && f.value.field === fieldName)
      .map((f) => ({ newDeadline: f.value!.date, annexNo: f.value!.annex_no }));

  const result = calculateCase({
    terms, penaltyEvents: events, asOf,
    handoverDeadline: ex.handover_deadline.value, transferDeadline: ex.transfer_deadline.value,
    handoverAmendments: amendments("handover_deadline"), transferAmendments: amendments("transfer_deadline"),
    actualHandoverDate: ex.actual_handover_date.value, actualTransferDate: ex.actual_transfer_date.value,
  }, cfg);
  return { result, blocking, warnings };
}

export const demanded = (p: PenaltyResult, capped: boolean) => (capped ? p.cappedGrosze : p.uncappedGrosze) ?? 0n;

/** Facts for the justification paragraph: dates, numbers and the clause quote; no party data. */
export function letterFacts(ex: Extraction, penalties: PenaltyResult[], capped: boolean) {
  const rate = ex.penalty_rate.value;
  return {
    penalty_clause_quote: ex.penalty_rate.quote ?? ex.penalty_basis.quote,
    penalty_rate: rate === null ? null
      : ex.penalty_basis.value === "percent_of_price_per_day" ? `${fmtPercent(dec(rate))} ceny za każdy dzień`
      : `${formatPln(plnToGrosze(dec(rate)))} za każdy dzień`,
    price: ex.price_gross.value !== null ? formatPln(plnToGrosze(dec(ex.price_gross.value))) : null,
    penalties: penalties.filter((p) => p.uncappedGrosze !== null).map((p) => ({
      event: EVENT_LABELS[p.event],
      deadline: fmtDate(p.effectiveDeadline.deadline),
      deadline_source: p.effectiveDeadline.source === "contract" ? "umowa" : `aneks${p.effectiveDeadline.annexNo !== null ? ` nr ${p.effectiveDeadline.annexNo}` : ""}`,
      actual_date: p.ongoing ? null : fmtDate(p.endDate),
      still_not_performed_as_of: p.ongoing ? fmtDate(p.endDate) : null,
      days_of_delay: p.days,
      amount_demanded: formatPln(demanded(p, capped)),
      cap_applied: capped && p.capReached,
    })),
    total_demanded: formatPln(penalties.reduce((a, p) => a + demanded(p, capped), 0n)),
    legal_basis: config.letter.legal_basis,
  };
}

const NUMBER = /\d[\d  .,]*\d|\d/g;
const normNum = (s: string) => s.replace(/[  ]/g, "").replace(/[.,]+$/, "");

/** Numbers in the model's text that do not appear in the facts. */
export function unsupportedNumbers(text: string, facts: unknown): string[] {
  const known = new Set((JSON.stringify(facts).match(NUMBER) ?? []).map(normNum));
  const found = (text.match(NUMBER) ?? []).map(normNum).filter((n) => n && !known.has(n));
  return [...new Set(found)].sort();
}
