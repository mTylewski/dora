// Parity with pipeline/anonymize.py: identical output, mapping and persons on the same synthetic texts.
import { describe, expect, it } from "vitest";
import parity from "./generated/anonymization_parity.json";
import { anonymizePages, findLeaks, restore, validIbanPl, validIdCard, validKw, validNip, validPesel, suspiciousWords, validRegon } from "./anonymize";

describe("anonymization parity with Python", () => {
  for (const c of parity.cases) {
    it(c.name, () => {
      const docs = new Map(Object.entries(c.documents as unknown as Record<string, string[]>));
      const { pages, anonymizer, persons } = anonymizePages(docs);
      expect(Object.fromEntries(pages)).toEqual(c.expected);
      expect(Object.fromEntries(anonymizer.mapping)).toEqual(c.mapping);
      expect(persons).toEqual(c.persons);
      for (const [id, original] of docs) {
        expect(pages.get(id)!.map((p) => restore(p, anonymizer.mapping))).toEqual(original);
        expect(findLeaks(pages.get(id)!.join(" "), c.secrets)).toEqual([]);
      }
    });
  }
});

describe("checksums", () => {
  it("rejects invalid values", () => {
    expect(validPesel("12345678901")).toBe(false);
    expect(validNip("1234567890")).toBe(false);
    expect(validRegon("123456789")).toBe(false);
    expect(validIdCard("ABC000000")).toBe(false);
    expect(validKw("WA1M/00012345/0")).toBe(false);
    expect(validIbanPl("1".repeat(26))).toBe(false);
  });
});

describe("review aid", () => {
  it("points at capitalized words left in the komparycja", () => {
    const text = "Akt notarialny. Stawili się:\nStrona kupująca Jan Testowy oraz Spółka Budowa Test, w Kancelarii Notarialnej.\nUmowa deweloperska";
    const { pages } = anonymizePages(new Map([["d", [text]]]));
    const words = suspiciousWords(pages.get("d")!);
    expect(words).toContain("Jan Testowy");
    expect(words).not.toContain("Kancelarii Notarialnej");
  });
});

