// App shell: login, menu and routing. Everything (cases, documents, settings, templates) is stored encrypted on this
// computer; only the approved anonymized text is sent to the analysis server.
import "./style.css";
import { renderBackup, renderLogin } from "./pages/account";
import { renderCase } from "./pages/case";
import { renderCases } from "./pages/cases";
import { renderFirm } from "./pages/firm";
import { renderHelp } from "./pages/help";
import { renderLetter } from "./pages/letter";
import { renderNewCase } from "./pages/newcase";
import { renderTemplates } from "./pages/templates";
import { inviteState } from "./api";
import { captureInvite } from "./invite";
import { getProfile, setVault } from "./store";
import { $, button, h, inviteSummary } from "./ui";
import type { Vault } from "./vault";

const LOCK_AFTER_MS = 30 * 60 * 1000;
let vault: Vault | null = null;
let lockTimer: ReturnType<typeof setTimeout> | undefined;

const app = () => $("#app");

const MENU: [string, string][] = [["#/cases", "Sprawy"], ["#/new", "Nowa sprawa"], ["#/firm", "Kancelaria"], ["#/templates", "Szablony"], ["#/backup", "Kopia zapasowa"], ["#/help", "Instrukcja"]];

async function renderNav() {
  const nav = $("#nav");
  if (!vault) { nav.replaceChildren(); return; }
  const [profile, invite] = await Promise.all([getProfile(), inviteState()]);
  const current = location.hash.split("/").slice(0, 2).join("/");
  nav.replaceChildren(
    ...MENU.map(([href, label]) => h("a", { href, ...(current === href ? { class: "active" } : {}) }, label)),
    invite.ok && invite.invite ? h("span", { class: "badge", title: `Zaproszenie: ${invite.invite.name}` }, inviteSummary(invite.invite)) : "",
    h("span", { class: "muted" }, profile.name || profile.email),
    button("Zablokuj", lock, "link"));
}

function lock() {
  vault?.lock();
  vault = null;
  setVault(null);
  clearTimeout(lockTimer);
  void route();
}

function resetLockTimer() {
  clearTimeout(lockTimer);
  if (vault) lockTimer = setTimeout(lock, LOCK_AFTER_MS);
}

async function route() {
  const root = app();
  await renderNav();
  if (!vault) {
    await renderLogin(root, (v) => { vault = v; resetLockTimer(); if (!location.hash || location.hash === "#/") location.hash = "#/cases"; else void route(); });
    return;
  }
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    switch (parts[0]) {
      case "new": return await renderNewCase(root);
      case "firm": return await renderFirm(root);
      case "templates": return await renderTemplates(root);
      case "help": return await renderHelp(root);
      case "backup": return renderBackup(root, vault);
      case "case":
        if (parts[2] === "letter") return await renderLetter(root, parts[1]);
        return await renderCase(root, parts[1]);
      default: return await renderCases(root);
    }
  } catch (e) {
    root.replaceChildren(h("p", { class: "alert error" }, `Błąd: ${e instanceof Error ? e.message : e}`));
  }
}

for (const ev of ["click", "keydown", "mousemove", "wheel", "scroll", "touchstart"]) document.addEventListener(ev, resetLockTimer, { passive: true, capture: true });
window.addEventListener("hashchange", () => void route());
window.addEventListener("dora-invite", () => void renderNav());
if (captureInvite()) void inviteState(true);
void route();
