import { describe, expect, it } from "vitest";
import parity from "./generated/letter_parity.json";
import { type LetterParties, PLACEHOLDERS, letterValues, missingFields } from "./letter";

const PARTIES: Record<string, LetterParties> = {
  full: {
    clients: [["Jan Testowy", "ul. Próbna 1, 00-001 Warszawa"], ["Anna Testowa", ""]],
    clientName: "Jan Testowy i Anna Testowa", developerName: "APM Test sp. z o.o.", developerAddress: "ul. Budowlana 2",
    agreementDate: "10.01.2023", agreementDeed: "Rep. A nr 100/2023", bankAccount: "11 1111 1111",
    caseNumber: "KAN/2026/001", lawyerName: "Anna Prawnicza", lawyerTitle: "radca prawny", lawyerRegistry: "WA-1",
    firmName: "Kancelaria Testowa", firmAddress: "ul. Testowa 1", city: "Warszawa", paymentDeadlineDays: 7, legalBasis: "",
  },
  empty: {},
};

describe("letter texts (parity with pipeline/letter.py)", () => {
  it("has the same placeholders", () => expect(PLACEHOLDERS).toEqual(parity.placeholders));
  for (const c of parity.cases) {
    it(c.name, () => {
      const total = c.name === "full" ? 680400n : 0n;
      const justification = c.name === "full" ? "Akapit." : "";
      expect(letterValues(PARTIES[c.parties], total, justification, "2026-10-06")).toEqual(c.values);
    });
  }
  it("lists missing fields", () => {
    expect(missingFields(letterValues({}, 0n, "", "2026-10-06"))).toContain("[UZUPEŁNIJ: numer rachunku]");
  });
});
