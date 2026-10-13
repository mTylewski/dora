// Parity tests: the same hand-calculated examples as calculator/tests (Python).
import { describe, expect, it } from "vitest";
import modelSchema from "../../schemas/extraction_model_output.json";
import {
  type CalcConfig, type Terms, calculateCase, computePenalty, dec, decToString, delayPeriod,
  effectiveDeadline, fmtPercent, formatPln, plnToGrosze, statutoryInterest,
} from "./calculator";
import { calculateFromExtraction, letterFacts, unsupportedNumbers } from "./adapter";
import { Extraction } from "./schema";
import { DocumentText, normalize, verifyExtraction } from "./verify";

const INCL: CalcConfig = { includeActualDate: true, interestYearDays: 365, verified: false };
const EXCL: CalcConfig = { ...INCL, includeActualDate: false };
const PRICE = plnToGrosze(dec("500000.00"));
const PCT: Terms = { basis: "percent_of_price_per_day", priceGrosze: PRICE, rate: dec(0.0002), cap: null, interestTable: null };
const pen = (terms = PCT, deadline = "2024-03-31", actual: string | null = "2024-05-15", cfg = INCL, asOf = "2025-01-01") =>
  computePenalty("handover_delay", deadline, [], actual, asOf, terms, cfg);

describe("decimals and money", () => {
  it("parses decimals exactly", () => {
    expect(dec(0.0002)).toEqual({ num: 2n, scale: 4 });
    expect(dec(1e-7)).toEqual({ num: 1n, scale: 7 });
    expect(dec("1.5e2")).toEqual({ num: 150n, scale: 0 });
    expect(decToString(dec("0.0500"))).toBe("0.05");
    expect(() => dec("abc")).toThrow();
  });
  it("formats", () => {
    expect(formatPln(123456789n)).toBe("1 234 567,89 zł");
    expect(formatPln(-150n)).toBe("-1,50 zł");
    expect(fmtPercent(dec(0.0002))).toBe("0,02%");
    expect(fmtPercent(dec(0.05))).toBe("5%");
    expect(fmtPercent(dec(1))).toBe("100%");
  });
});

describe("calculator (same examples as Python)", () => {
  it("counts days", () => {
    expect(delayPeriod("2024-03-31", "2024-05-15", INCL).days).toBe(45);
    expect(delayPeriod("2024-03-31", "2024-05-15", EXCL).days).toBe(44);
    expect(delayPeriod("2024-02-28", "2024-03-01", INCL).days).toBe(2);
    expect(delayPeriod("2024-03-31", "2024-03-01", INCL).days).toBe(0);
  });
  it("percent of price: 500 000 zł × 0,02% × 45 = 4 500 zł", () => {
    const r = pen();
    expect(r.uncappedGrosze).toBe(450_000n);
    expect(r.steps.at(-1)!.result).toBe(formatPln(450_000n));
    expect(pen(PCT, "2024-03-31", "2024-05-15", EXCL).uncappedGrosze).toBe(440_000n);
  });
  it("rounds once, half up", () => {
    const t: Terms = { ...PCT, priceGrosze: plnToGrosze(dec("412345.67")), rate: dec("0.0001") };
    expect(pen(t, "2024-01-01", "2024-01-04").uncappedGrosze).toBe(12_370n);
    const f: Terms = { ...PCT, basis: "fixed_per_day", rate: dec("0.125") };
    expect(pen(f, "2024-01-01", "2024-01-02").uncappedGrosze).toBe(13n);
  });
  it("fixed per day: 50 zł × 45 = 2 250 zł", () => {
    expect(pen({ ...PCT, basis: "fixed_per_day", rate: dec(50) }).uncappedGrosze).toBe(225_000n);
  });
  it("annex takes precedence, highest number wins", () => {
    expect(effectiveDeadline("2024-03-31", [{ newDeadline: "2024-09-30", annexNo: 2 }, { newDeadline: "2024-06-30", annexNo: 1 }]))
      .toEqual({ deadline: "2024-09-30", source: "annex", annexNo: 2 });
    expect(effectiveDeadline(null, [{ newDeadline: "2024-09-30", annexNo: null }, { newDeadline: "2024-06-30", annexNo: 3 }]).deadline)
      .toBe("2024-06-30");
    expect(() => effectiveDeadline(null, [])).toThrow();
  });
  it("percent cap: 100 000 zł capped at 25 000 zł", () => {
    const t: Terms = { ...PCT, rate: dec("0.001"), cap: { type: "percent", value: dec("0.05") } };
    const r = pen(t, "2024-01-01", "2024-07-19");
    expect([r.days, r.uncappedGrosze, r.capGrosze, r.cappedGrosze, r.capReached]).toEqual([200, 10_000_000n, 2_500_000n, 2_500_000n, true]);
  });
  it("ongoing delay uses as-of date", () => {
    const r = pen(PCT, "2024-03-31", null, INCL, "2024-04-10");
    expect([r.ongoing, r.days, r.uncappedGrosze]).toEqual([true, 10, 100_000n]);
  });
  it("other basis gives no amount", () => {
    expect(pen({ ...PCT, basis: "other" }).uncappedGrosze).toBeNull();
  });
  it("statutory interest split by periods: 220 000 gr", () => {
    const table = [
      { from: "2024-01-01", to: "2024-06-30", rate: dec("0.10"), source: "fixture A", verified: true },
      { from: "2024-07-01", to: null, rate: dec("0.12"), source: "fixture B", verified: false },
    ];
    const res = statutoryInterest(36_500_000n, "2024-06-21", "2024-07-10", table, INCL);
    expect(res.grosze).toBe(220_000n);
    expect(res.segments.map((s) => s.days)).toEqual([10, 10]);
    expect(res.allVerified).toBe(false);
  });
  it("case level totals and skipped events", () => {
    const res = calculateCase({
      terms: PCT, penaltyEvents: ["handover_delay", "transfer_delay"], asOf: "2025-01-01",
      handoverDeadline: "2024-03-31", transferDeadline: null,
      handoverAmendments: [{ newDeadline: "2024-04-30", annexNo: 1 }], transferAmendments: [],
      actualHandoverDate: "2024-05-15", actualTransferDate: null,
    }, INCL);
    expect(res.totalUncapped).toBe(150_000n);
    expect(res.skipped).toHaveLength(1);
    expect(res.timeline.map((t) => t.date)).toEqual([...res.timeline.map((t) => t.date)].sort());
  });
});

const PAGES = [
  "UMOWA DEWELOPERSKA zawarta w dniu 10 stycznia 2023 r.",
  "Cena brutto lokalu wynosi\n450.000,00 zł",
  "Deweloper wyda lokal do dnia 31 marca 2024 r.",
  "Kara 0,02% ceny za każdy dzień opóź-\nnienia w wydaniu lokalu.",
];
const f = (value: unknown, quote: string | null, page: number | null) =>
  ({ value, quote, page, document_id: "doc_1", confidence: "high" as const });
const EMPTY = f(null, null, null);
const EXTRACTION = {
  developer_name: EMPTY,
  agreement_reference: EMPTY,
  agreement_date: f("2023-01-10", "zawarta w dniu 10 stycznia 2023 r.", 1),
  price_gross: f(450000, "Cena brutto lokalu wynosi 450.000,00 zł", 2),
  handover_deadline: f("2024-03-31", "wyda lokal do dnia 31 marca 2024 r.", 3),
  transfer_deadline: EMPTY,
  annex_deadlines: [],
  penalty_basis: f("percent_of_price_per_day", "Kara 0,02% ceny za każdy dzień opóźnienia", 4),
  penalty_rate: f(0.0002, "Kara 0,02% ceny", 3),
  penalty_cap: EMPTY,
  penalty_events: f(["handover_delay"], "w wydaniu lokalu", 4),
  liability_exclusions: [],
  exclusive_penalty_clause: EMPTY,
  waiver_of_claims: EMPTY,
  actual_handover_date: f("2024-05-15", null, null),
  actual_transfer_date: EMPTY,
};

describe("schema and verification", () => {
  it("zod schema matches the generated JSON schema field names", () => {
    const jsonFields = Object.keys((modelSchema as { properties: object }).properties).sort();
    expect(Object.keys(Extraction.shape).sort()).toEqual(jsonFields);
    expect(Extraction.safeParse(EXTRACTION).success).toBe(true);
    expect(Extraction.safeParse({ ...EXTRACTION, extra: 1 }).success).toBe(false);
  });
  it("normalizes like Python", () => {
    expect(normalize("  a  b\n\tc ")).toBe("a b c");
    expect(normalize("„x” – y")).toBe('"x" - y');
    expect(normalize("opóź-\nnienia", true)).toBe("opóźnienia");
    expect(new DocumentText(["ab", "cd"]).find("b cd")).toEqual([1]);
  });
  it("verifies quotes and pages", () => {
    const ex = Extraction.parse(EXTRACTION);
    const { issues, needsReview } = verifyExtraction(ex, new Map([["doc_1", PAGES]]));
    expect(issues).toEqual([
      { path: "penalty_rate", issue: "page_mismatch", found_page: 4 },
      { path: "actual_handover_date", issue: "quote_missing" },
    ]);
    expect([...needsReview]).toEqual(["penalty_rate", "actual_handover_date"]);
  });
  it("calculates from extraction and builds letter facts", () => {
    const ex = Extraction.parse(EXTRACTION);
    const out = calculateFromExtraction(ex, "2025-01-01", new Set(["penalty_rate"]));
    // 450 000 zł × 0,02% × 45 = 4 050 zł
    expect(out.result!.totalUncapped).toBe(405_000n);
    expect(out.warnings[0]).toContain("stawka kary");
    const facts = letterFacts(ex, out.result!.penalties, false);
    expect(facts.total_demanded).toBe("4 050,00 zł");
    expect(facts.penalty_rate).toBe("0,02% ceny za każdy dzień");
    expect(unsupportedNumbers("Kwota 4 050,00 zł za 45 dni.", facts)).toEqual([]);
    expect(unsupportedNumbers("Kwota 5000 zł.", facts)).toEqual(["5000"]);
  });
  it("flags agreements from before the new development act", () => {
    const old = Extraction.parse({ ...EXTRACTION, agreement_date: f("2021-05-14", "q", 1) });
    expect(calculateFromExtraction(old, "2025-01-01", new Set()).warnings.some((w) => w.includes("przed 01.07.2022"))).toBe(true);
    const fresh = Extraction.parse(EXTRACTION);
    expect(calculateFromExtraction(fresh, "2025-01-01", new Set()).warnings.some((w) => w.includes("przejściowe"))).toBe(false);
  });
  it("warns about a waiver of claims", () => {
    const ex = Extraction.parse({ ...EXTRACTION, waiver_of_claims: f(true, "nie ma żadnych roszczeń", 1) });
    expect(calculateFromExtraction(ex, "2025-01-01", new Set()).warnings.some((w) => w.includes("zrzeczeniu"))).toBe(true);
  });
  it("blocks without price", () => {
    const ex = Extraction.parse({ ...EXTRACTION, price_gross: EMPTY });
    expect(calculateFromExtraction(ex, "2025-01-01", new Set()).blocking).toEqual(["Brak ceny lokalu."]);
  });
});
