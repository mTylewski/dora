import { describe, expect, it } from "vitest";
import worker, { type Env, renderDocument, residualIdentifiers } from "./index";
import { inviteStatus, type Invite } from "./invites";

const env: Env = { ANTHROPIC_API_KEY: "test", ALLOWED_ORIGINS: "https://demo.example", MAX_DOCUMENTS: "2", MAX_TOTAL_CHARS: "5000", INVITES_REQUIRED: "false" };
const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;
const call = (path: string, init: RequestInit & { origin?: string } = {}) =>
  worker.fetch(new Request(`https://api.example${path}`, {
    ...init, headers: { "Content-Type": "application/json", Origin: init.origin ?? "https://demo.example" },
  }), env, ctx);
const post = (path: string, body: unknown) => call(path, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) });

describe("worker", () => {
  it("answers CORS preflight only for allowed origins", async () => {
    const ok = await call("/api/analyze", { method: "OPTIONS" });
    expect(ok.status).toBe(204);
    expect(ok.headers.get("Access-Control-Allow-Origin")).toBe("https://demo.example");
    expect((await call("/api/analyze", { method: "OPTIONS", origin: "https://evil.example" })).status).toBe(403);
    expect((await call("/api/analyze", { method: "POST", body: "{}", origin: "https://evil.example" })).status).toBe(403);
  });

  it("accepts only anonymized text documents", async () => {
    expect((await post("/api/analyze", "not json")).status).toBe(400);
    expect((await post("/api/analyze", { documents: [] })).status).toBe(400);
    // the old PDF format is rejected
    expect((await post("/api/analyze", { documents: [{ name: "a.pdf", data: "JVBERi0=" }] })).status).toBe(400);
  });

  it("rejects text that still contains personal identifiers", async () => {
    const r = await post("/api/analyze", { documents: [{ id: "doc_1", pages: ["Nabywca: [OSOBA_1], PESEL: 90010112349."] }] });
    expect(r.status).toBe(422);
    expect(await r.json()).toEqual({ error: "pii_detected", labels: ["PESEL"] });
    const j = await post("/api/justification", { facts: { note: "konto 46 1240 1037 0000 1234 5678 9012" } });
    expect(j.status).toBe(422);
  });

  it("enforces size and count limits", async () => {
    expect((await post("/api/analyze", { documents: [{ id: "doc_1", pages: ["x".repeat(6000)] }] })).status).toBe(413);
    const three = ["doc_1", "doc_2", "doc_3"].map((id) => ({ id, pages: ["tekst"] }));
    expect((await post("/api/analyze", { documents: three })).status).toBe(413);
    expect((await post("/api/justification", "x".repeat(30_000))).status).toBe(413);
  });

  it("404 for unknown paths", async () => {
    expect((await call("/nope", { method: "GET" })).status).toBe(404);
  });
});

describe("helpers", () => {
  it("renders documents like the Python pipeline", () => {
    expect(renderDocument({ id: "doc_1", pages: ["A", "B", "C"], type: "annex" }, 2))
      .toBe('<document id="doc_1" type="annex">\n<page number="1">\nA\n</page>\n<page number="2">\nB\n</page>\n</document>');
  });
  it("finds no residual identifiers in anonymized text", () => {
    expect(residualIdentifiers([{ id: "doc_1", pages: ["Nabywca: [OSOBA_1], PESEL: [PESEL_1], cena 450.000,00 zł, 31-03-2024"] }])).toEqual([]);
  });
});

/** Minimal in-memory KV for tests. */
function fakeKv(): KVNamespace {
  const store = new Map<string, { value: string; metadata: unknown }>();
  return {
    async get(key: string, type?: string) { const e = store.get(key); return e ? (type === "json" ? JSON.parse(e.value) : e.value) : null; },
    async put(key: string, value: string, opts?: { metadata?: unknown }) { store.set(key, { value, metadata: opts?.metadata ?? null }); },
    async list({ prefix = "" }: { prefix?: string } = {}) {
      return { keys: [...store].filter(([k]) => k.startsWith(prefix)).map(([name, e]) => ({ name, metadata: e.metadata })), list_complete: true, cursor: "" };
    },
  } as unknown as KVNamespace;
}

describe("invites", () => {
  const ADMIN_KEY = "a".repeat(32);
  const ienv: Env = { ...env, INVITES_REQUIRED: undefined, INVITES: fakeKv(), ADMIN_KEY };
  const req = (path: string, init: { method?: string; body?: unknown; token?: string; admin?: string } = {}) =>
    worker.fetch(new Request(`https://api.example${path}`, {
      method: init.method ?? "GET",
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      headers: {
        "Content-Type": "application/json", Origin: "https://demo.example",
        ...(init.token ? { Authorization: `Bearer ${init.token}` } : {}), ...(init.admin ? { "X-Admin-Key": init.admin } : {}),
      },
    }), ienv, ctx);
  const piiDoc = { documents: [{ id: "doc_1", pages: ["PESEL: 90010112349"] }] };

  it("requires the admin key for admin endpoints", async () => {
    expect((await req("/api/admin/invites")).status).toBe(401);
    expect((await req("/api/admin/invites", { admin: "b".repeat(32) })).status).toBe(401);
    expect((await req("/api/admin/invites", { admin: ADMIN_KEY })).status).toBe(200);
  });

  it("creates, checks, tops up and revokes an invitation", async () => {
    expect((await req("/api/analyze", { method: "POST", body: piiDoc })).status).toBe(401);
    expect((await req("/api/invite", { token: "x".repeat(22) })).status).toBe(401);

    const created = await req("/api/admin/invites", { method: "POST", admin: ADMIN_KEY, body: { name: "Kancelaria Testowa", limit: 2, days: 30 } });
    expect(created.status).toBe(201);
    const { token, invite } = (await created.json()) as { token: string; invite: { id: string } };
    expect(token).toMatch(/^[A-Za-z0-9_-]{24}$/);

    const info = (await (await req("/api/invite", { token })).json()) as { invite: { name: string; limit: number; used: number } };
    expect(info.invite).toMatchObject({ name: "Kancelaria Testowa", limit: 2, used: 0 });
    // rejected text (personal data) does not use up the limit
    expect((await req("/api/analyze", { method: "POST", token, body: piiDoc })).status).toBe(422);
    expect(((await (await req("/api/invite", { token })).json()) as { invite: { used: number } }).invite.used).toBe(0);

    const topped = await req(`/api/admin/invites/${invite.id}/topup`, { method: "POST", admin: ADMIN_KEY, body: { add: 5 } });
    expect(((await topped.json()) as { invite: { limit: number } }).invite.limit).toBe(7);

    expect((await req(`/api/admin/invites/${invite.id}/revoke`, { method: "POST", admin: ADMIN_KEY, body: {} })).status).toBe(200);
    const revoked = await req("/api/analyze", { method: "POST", token, body: piiDoc });
    expect(revoked.status).toBe(403);
    expect(await revoked.json()).toEqual({ error: "invite_revoked" });
  });

  it("validates admin input", async () => {
    expect((await req("/api/admin/invites", { method: "POST", admin: ADMIN_KEY, body: { name: "", limit: 3 } })).status).toBe(400);
    expect((await req("/api/admin/invites/0123456789/revoke", { method: "POST", admin: ADMIN_KEY, body: {} })).status).toBe(404);
  });
});

describe("invite status", () => {
  const base: Invite = { id: "x", name: "n", limit: 2, used: 0, letters: 0, createdAt: "2026-10-01T00:00:00Z", expiresAt: "2026-10-31T00:00:00Z", revoked: false };
  const now = new Date("2026-10-06T12:00:00Z");
  it("checks expiry, revocation and limits", () => {
    expect(inviteStatus(base, now)).toBe("ok");
    expect(inviteStatus(null, now)).toBe("invite_invalid");
    expect(inviteStatus({ ...base, used: 2 }, now)).toBe("invite_exhausted");
    expect(inviteStatus({ ...base, used: 2 }, now, false)).toBe("ok");
    expect(inviteStatus({ ...base, letters: 20 }, now, false)).toBe("invite_exhausted");
    expect(inviteStatus({ ...base, revoked: true }, now)).toBe("invite_revoked");
    expect(inviteStatus(base, new Date("2026-11-01T00:00:00Z"))).toBe("invite_expired");
  });
});
