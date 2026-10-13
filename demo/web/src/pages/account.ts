// Account on this computer: create, unlock, restore from backup, backup, remove all data.
import { setVault } from "../store";
import { button, download, h, input, labeled } from "../ui";
import { Vault } from "../vault";
import { overview } from "./help";

export async function renderLogin(root: HTMLElement, onUnlocked: (v: Vault) => void) {
  const exists = await Vault.exists();
  const error = h("p", { class: "alert error", hidden: "" });
  const fail = (msg: string) => { error.textContent = msg; error.hidden = false; };
  const busy = (b: HTMLButtonElement, text: string) => { b.disabled = true; b.textContent = text; };

  if (exists) {
    const password = input("password", "", { type: "password", autocomplete: "current-password" });
    const unlock = button("Odblokuj", async () => {
      busy(unlock, "Odblokowywanie…");
      const v = await Vault.unlock(password.value);
      if (!v) { unlock.disabled = false; unlock.textContent = "Odblokuj"; fail("Nieprawidłowe hasło."); return; }
      setVault(v);
      onUnlocked(v);
    });
    password.addEventListener("keydown", (e) => { if (e.key === "Enter") unlock.click(); });
    const reset = h("details", { class: "small" }, h("summary", {}, "Nie pamiętam hasła"),
      h("p", {}, "Hasła nie da się odzyskać — dane są nim zaszyfrowane. Możesz odtworzyć dane z kopii zapasowej (ona też wymaga hasła, którego użyto przy jej tworzeniu) albo usunąć wszystkie dane z tego komputera i założyć konto od nowa."),
      restoreBox(root, onUnlocked), dangerReset(root, onUnlocked));
    root.replaceChildren(h("section", { class: "card narrow" }, h("h1", {}, "Odblokuj"),
      h("p", { class: "muted" }, "Sprawy i ustawienia są zaszyfrowane na tym komputerze Twoim hasłem."),
      h("div", { class: "stack" }, labeled("Hasło", password), unlock, error), reset));
    password.focus();
    return;
  }

  const name = input("name", "", { autocomplete: "name" });
  const email = input("email", "", { type: "email", autocomplete: "email" });
  const p1 = input("password", "", { type: "password", autocomplete: "new-password", minlength: "10" });
  const p2 = input("password2", "", { type: "password", autocomplete: "new-password" });
  const create = button("Załóż konto", async () => {
    if (p1.value.length < 10) return fail("Hasło musi mieć co najmniej 10 znaków.");
    if (p1.value !== p2.value) return fail("Hasła nie są zgodne.");
    busy(create, "Zakładanie konta…");
    try {
      const v = await Vault.create(p1.value, { name: name.value.trim(), email: email.value.trim() });
      setVault(v);
      onUnlocked(v);
    } catch (e) {
      create.disabled = false;
      create.textContent = "Załóż konto";
      fail(e instanceof Error ? e.message : String(e));
    }
  });
  root.replaceChildren(h("div", { class: "welcome" }, overview(), h("section", { class: "card" }, h("h1", {}, "Pierwsze uruchomienie"),
    h("p", {}, "Załóż konto na tym komputerze. Hasło szyfruje wszystkie sprawy, dokumenty i ustawienia zapisane w przeglądarce. ",
      h("strong", {}, "Hasła nie da się odzyskać"), " — zapisz je w menedżerze haseł kancelarii."),
    h("div", { class: "stack" }, labeled("Imię i nazwisko", name), labeled("E-mail", email), labeled("Hasło (min. 10 znaków)", p1), labeled("Powtórz hasło", p2), create, error),
    h("details", { class: "small" }, h("summary", {}, "Mam kopię zapasową z innego komputera"), restoreBox(root, onUnlocked)))));
}

function restoreBox(root: HTMLElement, onUnlocked: (v: Vault) => void) {
  const file = input("backup", "", { type: "file", accept: ".kopia,application/octet-stream,application/json" });
  const password = input("backupPassword", "", { type: "password" });
  const msg = h("p", { class: "alert error", hidden: "" });
  const restore = button("Odtwórz z kopii", async () => {
    const f = file.files?.[0];
    if (!f) { file.focus(); return; }
    restore.disabled = true;
    try {
      if (!(await Vault.importBackup(await f.text(), password.value))) throw new Error("Hasło nie pasuje do tej kopii.");
      const v = (await Vault.unlock(password.value))!;
      setVault(v);
      onUnlocked(v);
    } catch (e) {
      restore.disabled = false;
      msg.textContent = e instanceof Error ? e.message : String(e);
      msg.hidden = false;
    }
  }, "secondary");
  void root;
  return h("div", { class: "stack" }, h("p", { class: "muted small" }, "Odtworzenie zastępuje dane zapisane na tym komputerze."),
    labeled("Plik kopii", file), labeled("Hasło użyte przy tworzeniu kopii", password), restore, msg);
}

function dangerReset(root: HTMLElement, onUnlocked: (v: Vault) => void) {
  const confirm = h("input", { type: "checkbox" }) as HTMLInputElement;
  return h("div", { class: "stack" }, h("label", { class: "row" }, confirm, " Rozumiem, że wszystkie sprawy na tym komputerze zostaną usunięte."),
    button("Usuń dane i załóż nowe konto", async () => {
      if (!confirm.checked) { confirm.focus(); return; }
      await Vault.destroy();
      await renderLogin(root, onUnlocked);
    }, "danger"));
}

export function renderBackup(root: HTMLElement, vault: Vault) {
  root.replaceChildren(h("h1", {}, "Kopia zapasowa"),
    h("section", { class: "card" },
      h("p", {}, "Sprawy, dokumenty i ustawienia są zapisane tylko na tym komputerze, w przeglądarce. Wyczyszczenie danych przeglądarki albo awaria dysku je usuwa — dlatego rób regularnie kopię zapasową."),
      h("p", {}, "Plik kopii jest zaszyfrowany tym samym hasłem co konto. Bez hasła nikt go nie odczyta, także w razie zgubienia pliku. Przechowuj go np. na zaszyfrowanym dysku kancelarii."),
      button("Pobierz kopię zapasową", async () => {
        const blob = await vault.exportBackup();
        download(blob, `kopia_analiza_roszczen_${new Date().toISOString().slice(0, 10)}.kopia`);
      })));
}
