// Same cases as app/tests/test_corrections.py.
import { describe, expect, it } from "vitest";
import {
  CorrectionError, amountInQuote, applyCorrections, editValue, formatAmountInput, parseDate, parseNumber, parseValue,
  valueMatchesQuote,
} from "./corrections";
import { Extraction } from "./schema";

describe("corrections", () => {
  it.each([
    ["1.080.000,00", 1080000], ["1 080 000,00 zł", 1080000], ["1 080 000,00", 1080000],
    ["1080000,00", 1080000], ["1080000.5", 1080000.5], ["0,0001", 0.0001], ["1.080.000", 1080000],
  ])("parses Polish number %s", (raw, expected) => expect(parseNumber(raw)).toBe(expected));

  it("rejects invalid input", () => {
    expect(() => parseNumber("abc")).toThrow(CorrectionError);
    expect(() => parseDate("31.02.2024")).toThrow(CorrectionError);
    expect(() => parseValue("bool", "może")).toThrow(CorrectionError);
  });

  it("parses dates, caps, booleans and empty values", () => {
    expect(parseDate("1.9.2026")).toBe("2026-09-01");
    expect(parseDate("2026-09-01")).toBe("2026-09-01");
    expect(parseValue("cap", "5%")).toEqual({ type: "percent", value: 0.05 });
    expect(parseValue("cap", "20 000")).toEqual({ type: "amount", value: 20000 });
    expect(parseValue("bool", "tak")).toBe(true);
    expect(parseValue("date", "")).toBeNull();
  });

  it("checks values against quotes", () => {
    const quote = "za cenę w kwocie brutto 1.080.000,00 zł (jeden milion osiemdziesiąt tysięcy złotych)";
    expect(valueMatchesQuote("price_gross", 1080000, quote)).toBe(true);
    expect(valueMatchesQuote("price_gross", 108000000, quote)).toBe(false);
    expect(valueMatchesQuote("penalty_rate", 0.0001, "w wysokości 0,01 % ceny")).toBe(true);
    expect(valueMatchesQuote("penalty_cap", { type: "percent", value: 0.05 }, "nie więcej niż 5% ceny")).toBe(true);
    expect(valueMatchesQuote("price_gross", 1, "brak liczb")).toBeNull();
    expect(amountInQuote(quote)).toBe(1080000);
    expect(amountInQuote("cena 500.000,00 zł, w tym VAT 37.037,04 zł")).toBeNull();
  });

  it("formats edit values and typed amounts", () => {
    expect(editValue("price_gross", 1080000)).toBe("1 080 000,00");
    expect(editValue("penalty_cap", { type: "percent", value: 0.05 })).toBe("5%");
    expect(editValue("actual_transfer_date", "2026-09-01")).toBe("01.09.2026");
    let typed = "";
    for (const ch of "1080000.00") typed = formatAmountInput(typed + ch);
    expect(typed).toBe("1 080 000.00");
    expect(formatAmountInput("1.080.000,00")).toBe("1 080 000,00");
  });

  it("applies corrections without touching the original", () => {
    const empty = { value: null, quote: null, page: null, document_id: null, confidence: "low" as const };
    const original = Extraction.parse({
      developer_name: empty, agreement_reference: empty, agreement_date: empty, price_gross: empty,
      handover_deadline: empty, transfer_deadline: empty, annex_deadlines: [], penalty_basis: empty, penalty_rate: empty,
      penalty_cap: empty, penalty_events: empty, liability_exclusions: [], exclusive_penalty_clause: empty,
      waiver_of_claims: empty, actual_handover_date: empty, actual_transfer_date: empty,
    });
    const fixed = applyCorrections(original, new Map([["price_gross", { value: 1080000, confirmed: false }]]));
    expect(fixed.price_gross.value).toBe(1080000);
    expect(fixed.price_gross.confidence).toBe("high");
    expect(original.price_gross.value).toBeNull();
  });
});
