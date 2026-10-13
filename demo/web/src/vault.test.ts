import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Key derivation is deliberately slow (600 000 PBKDF2 iterations).
vi.setConfig({ testTimeout: 60_000, hookTimeout: 60_000 });
import { Vault } from "./vault";

describe("vault", () => {
  beforeEach(async () => { await Vault.destroy(); });

  it("creates an account, stores encrypted records and unlocks only with the right password", async () => {
    expect(await Vault.exists()).toBe(false);
    const v = await Vault.create("bardzo-tajne-haslo", { name: "Anna Prawnicza", email: "a@kancelaria.test" });
    await v.put("case", "c1", { title: "Sprawa testowa", amount: 6804 });
    await v.putBytes("case-pdf", "c1/doc_1", new Uint8Array([37, 80, 68, 70]));
    v.lock();

    expect(await Vault.exists()).toBe(true);
    expect(await Vault.unlock("złe-hasło-123")).toBeNull();
    const again = (await Vault.unlock("bardzo-tajne-haslo"))!;
    expect(await again.get("case", "c1")).toEqual({ title: "Sprawa testowa", amount: 6804 });
    expect([...(await again.getBytes("case-pdf", "c1/doc_1"))!]).toEqual([37, 80, 68, 70]);
    expect((await again.list<{ name: string }>("profile"))[0].value.name).toBe("Anna Prawnicza");
    again.lock();
  });

  it("keeps the content unreadable in the database", async () => {
    const v = await Vault.create("bardzo-tajne-haslo", { name: "X", email: "" });
    await v.put("case", "c1", { title: "Jan Testowy PESEL" });
    const backup = await (await v.exportBackup()).text();
    expect(backup).not.toContain("Jan Testowy");
    expect(backup).not.toContain("PESEL");
    v.lock();
  });

  it("restores a backup only with its password and deletes by prefix", async () => {
    const v = await Vault.create("bardzo-tajne-haslo", { name: "X", email: "" });
    await v.put("case", "c1", { title: "A" });
    await v.put("case-pdf", "c1/doc_1", { x: 1 });
    await v.put("case-pdf", "c2/doc_1", { x: 2 });
    await v.deletePrefix("case-pdf", "c1/");
    expect((await v.list("case-pdf")).map((r) => r.id)).toEqual(["c2/doc_1"]);
    const backup = await (await v.exportBackup()).text();
    v.lock();
    await Vault.destroy();

    expect(await Vault.importBackup(backup, "zle-haslo-xyz")).toBe(false);
    expect(await Vault.importBackup(backup, "bardzo-tajne-haslo")).toBe(true);
    const restored = (await Vault.unlock("bardzo-tajne-haslo"))!;
    expect(await restored.get("case", "c1")).toEqual({ title: "A" });
    restored.lock();
  });

  it("rejects short passwords and a second account", async () => {
    await expect(Vault.create("krotkie", { name: "", email: "" })).rejects.toThrow();
    (await Vault.create("bardzo-tajne-haslo", { name: "", email: "" })).lock();
    await expect(Vault.create("inne-dlugie-haslo", { name: "", email: "" })).rejects.toThrow("Konto już istnieje");
  });
});
