// @vitest-environment happy-dom
// Smoke test of the pages in a simulated browser: account, firm and lawyers, cases list, templates, backup.
import "fake-indexeddb/auto";
import { describe, expect, it, vi } from "vitest";
import { renderBackup, renderLogin } from "./pages/account";
import { renderCases } from "./pages/cases";
import { renderFirm } from "./pages/firm";
import { renderHelp } from "./pages/help";
import { renderTemplates } from "./pages/templates";
import { getFirm, getProfile, listLawyers, nextCaseNumber, saveCase, setVault } from "./store";
import { Vault } from "./vault";

vi.setConfig({ testTimeout: 60_000 });
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root: ParentNode, text: string) =>
  [...root.querySelectorAll("button")].find((b) => b.textContent?.includes(text)) as HTMLButtonElement;

describe("pages", () => {
  it("creates an account, saves firm data and a lawyer, lists cases", async () => {
    await Vault.destroy();
    const root = document.createElement("main");
    let unlocked: Vault | null = null;
    await renderLogin(root, (v) => { unlocked = v; });
    expect(root.textContent).toContain("Pierwsze uruchomienie");
    expect(root.textContent).toContain("Witaj w DORA");
    (root.querySelector('input[name="name"]') as HTMLInputElement).value = "Anna Prawnicza";
    (root.querySelector('input[name="password"]') as HTMLInputElement).value = "bardzo-tajne-haslo";
    (root.querySelector('input[name="password2"]') as HTMLInputElement).value = "bardzo-tajne-haslo";
    byText(root, "Załóż konto").click();
    for (let i = 0; i < 200 && !unlocked; i++) await new Promise((r) => setTimeout(r, 20));
    expect(unlocked).not.toBeNull();
    setVault(unlocked);
    expect((await getProfile()).name).toBe("Anna Prawnicza");

    await renderFirm(root);
    (root.querySelector('input[name="name"]') as HTMLInputElement).value = "Kancelaria Testowa";
    (root.querySelector('input[name="city"]') as HTMLInputElement).value = "Warszawa";
    byText(root, "Zapisz").click();
    for (let i = 0; i < 50 && !(await getFirm()).name; i++) await tick();
    expect((await getFirm()).city).toBe("Warszawa");

    const rows = root.querySelectorAll("tbody tr");
    const newRow = rows[rows.length - 1];
    (newRow.querySelector('input[name="fullName"]') as HTMLInputElement).value = "Jan Kowalski";
    (newRow.querySelector('input[type="radio"]') as HTMLInputElement | null)?.click();
    byText(newRow, "Dodaj").click();
    for (let i = 0; i < 50 && !(await listLawyers()).length; i++) await tick();
    expect((await listLawyers())[0].fullName).toBe("Jan Kowalski");
    for (let i = 0; i < 50 && !(await getProfile()).lawyerId; i++) await tick();

    await renderCases(root);
    expect(root.textContent).toContain("Brak spraw");
    expect(root.textContent).toContain("Jak zacząć (2/4)");
    byText(root, "Ukryj").click();
    for (let i = 0; i < 50 && root.textContent?.includes("Jak zacząć"); i++) await tick();
    expect(root.textContent).not.toContain("Jak zacząć");
    await renderHelp(root);
    expect(root.textContent).toContain("Czego DORA nie robi");
    expect(root.textContent).toContain("Pokaż znowu panel");
    await saveCase({
      id: "c1", title: "Sprawa testowa", caseNumber: "KAN/2026/001", lawyerId: "", createdAt: new Date().toISOString(),
      asOf: "2026-10-06", status: "error", errorCode: "rate_limited", documents: [], mapping: [], persons: [],
      replacements: [], analysis: null, corrections: [],
    });
    await renderCases(root);
    expect(root.textContent).toContain("Sprawa testowa");
    expect(root.textContent).toContain("KAN/2026/001");

    await renderTemplates(root);
    expect(root.textContent).toContain("szablon domyślny");
    expect(root.textContent).toContain("{{case_number}}");

    renderBackup(root, unlocked!);
    expect(root.textContent).toContain("Pobierz kopię zapasową");
    unlocked!.lock();
  });

  it("numbers cases per year", () => {
    const now = new Date("2026-10-06");
    expect(nextCaseNumber("KAN/{rok}/{nr}", [], now)).toBe("KAN/2026/001");
    expect(nextCaseNumber("KAN/{rok}/{nr}", ["KAN/2026/001", "KAN/2026/007", "KAN/2025/050", "INNA"], now)).toBe("KAN/2026/008");
    expect(nextCaseNumber("SPR", [], now)).toBe("SPR/001");
  });
});
