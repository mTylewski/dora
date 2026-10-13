// Invitation links for the hosted demo.
//
//   npm run invite -- create --name "Kancelaria Nowak" [--limit 10] [--days 30]
//   npm run invite -- list
//   npm run invite -- topup <id> --add 10
//   npm run invite -- extend <id> --days 14
//   npm run invite -- revoke <id>
//   add --local to work against the local server (wrangler dev) instead of the published one
//
// Published addresses come from .deploy.json (written at deploy time, not in git).
// The admin key comes from the DORA_ADMIN_KEY environment variable (or ADMIN_KEY in .dev.vars for --local).
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
};
const local = args.includes("--local");
const positional = args.filter((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--") && args[i - 1] !== "--local"));
const [command, id] = positional;

function fail(msg) {
  console.error(msg);
  process.exit(1);
}

function devVar(name) {
  const file = join(root, ".dev.vars");
  if (!existsSync(file)) return undefined;
  const line = readFileSync(file, "utf8").split(/\r?\n/).find((l) => l.startsWith(`${name}=`));
  return line?.slice(name.length + 1).trim().replace(/^"|"$/g, "");
}

const deploy = existsSync(join(root, ".deploy.json")) ? JSON.parse(readFileSync(join(root, ".deploy.json"), "utf8")) : {};
const api = local ? "http://127.0.0.1:8787" : deploy.apiUrl;
const app = local ? "http://127.0.0.1:5173" : deploy.appUrl;
const key = (local ? devVar("ADMIN_KEY") : undefined) ?? process.env.DORA_ADMIN_KEY;
if (!api || !app) fail("Brak adresów usługi (.deploy.json). Użyj --local albo najpierw opublikuj usługę.");
if (!key) fail("Brak klucza administratora (zmienna środowiskowa DORA_ADMIN_KEY).");

async function call(method, path, body) {
  const res = await fetch(api + path, {
    method, headers: { "Content-Type": "application/json", "X-Admin-Key": key }, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) fail(`Błąd ${res.status}: ${data.error ?? "nieznany"}`);
  return data;
}

const date = (iso) => new Date(iso).toLocaleDateString("pl-PL");
const row = (inv) => {
  const state = inv.revoked ? "WYŁĄCZONE" : new Date(inv.expiresAt) < new Date() ? "WYGASŁO" : inv.used >= inv.limit ? "LIMIT" : "aktywne";
  return `${inv.id}  ${String(inv.used).padStart(3)}/${String(inv.limit).padEnd(4)} do ${date(inv.expiresAt).padEnd(11)} ${state.padEnd(10)} ${inv.name}`;
};

switch (command) {
  case "create": {
    const name = flag("name");
    if (!name) fail('Podaj nazwę: --name "Kancelaria Nowak"');
    const { token, invite } = await call("POST", "/api/admin/invites", { name, limit: Number(flag("limit", 10)), days: Number(flag("days", 30)) });
    console.log(`\nZaproszenie dla: ${invite.name}`);
    console.log(`Limit: ${invite.limit} analiz, ważne do ${date(invite.expiresAt)} (id: ${invite.id})\n`);
    console.log(`Link do wysłania:\n${app}/#/z/${token}\n`);
    console.log("Link pokazuje się tylko teraz — skopiuj go. Później można go tylko wyłączyć (revoke) i utworzyć nowy.");
    break;
  }
  case "list": {
    const { invites } = await call("GET", "/api/admin/invites");
    if (!invites.length) console.log("Brak zaproszeń.");
    else console.log(`id          zużyte     ważne do    stan       dla kogo\n${invites.map(row).join("\n")}`);
    break;
  }
  case "topup":
    if (!id) fail("Podaj id zaproszenia (z: npm run invite -- list)");
    console.log(row((await call("POST", `/api/admin/invites/${id}/topup`, { add: Number(flag("add", 10)) })).invite));
    break;
  case "extend":
    if (!id) fail("Podaj id zaproszenia (z: npm run invite -- list)");
    console.log(row((await call("POST", `/api/admin/invites/${id}/extend`, { days: Number(flag("days", 14)) })).invite));
    break;
  case "revoke":
    if (!id) fail("Podaj id zaproszenia (z: npm run invite -- list)");
    console.log(row((await call("POST", `/api/admin/invites/${id}/revoke`, {})).invite));
    break;
  default:
    fail('Użycie: npm run invite -- create --name "Kancelaria Nowak" [--limit 10] [--days 30] | list | topup <id> --add 10 | extend <id> --days 14 | revoke <id>  [--local]');
}
