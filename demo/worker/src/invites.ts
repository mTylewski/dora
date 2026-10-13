// Invitation links for the hosted demo: each link carries a random token; the Worker keeps only its SHA-256 hash
// together with the holder's name, the analysis limit, the expiry date and the usage counter (KV namespace INVITES).
// Admin endpoints (create / list / top up / revoke) require the ADMIN_KEY secret and are used by scripts/invite.mjs.

export interface Invite {
  id: string; // first 10 hex chars of the hash, shown to the admin
  name: string;
  limit: number;
  used: number;
  letters: number; // justification calls (not counted towards the limit, capped separately)
  createdAt: string;
  expiresAt: string;
  revoked: boolean;
  lastUsedAt?: string;
}

export type InviteStatus = "ok" | "invite_missing" | "invite_invalid" | "invite_expired" | "invite_revoked" | "invite_exhausted";

const PREFIX = "inv:";
const LETTERS_PER_ANALYSIS = 10;

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function newToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(18)); // 144 bits
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function bearer(request: Request): string | null {
  const m = /^Bearer ([A-Za-z0-9_-]{16,64})$/.exec(request.headers.get("Authorization") ?? "");
  return m ? m[1] : null;
}

const save = (kv: KVNamespace, hash: string, inv: Invite) => kv.put(PREFIX + hash, JSON.stringify(inv), { metadata: inv });

export async function loadInvite(kv: KVNamespace, token: string | null): Promise<{ hash: string; invite: Invite } | null> {
  if (!token) return null;
  const hash = await sha256Hex(token);
  const invite = await kv.get<Invite>(PREFIX + hash, "json");
  return invite ? { hash, invite } : null;
}

export function inviteStatus(invite: Invite | null, now = new Date(), forAnalysis = true): InviteStatus {
  if (!invite) return "invite_invalid";
  if (invite.revoked) return "invite_revoked";
  if (now.toISOString() > invite.expiresAt) return "invite_expired";
  if (forAnalysis && invite.used >= invite.limit) return "invite_exhausted";
  if (!forAnalysis && invite.letters >= Math.max(invite.limit, 1) * LETTERS_PER_ANALYSIS) return "invite_exhausted";
  return "ok";
}

/** Public view for the browser (no hash, no admin details). */
export const publicView = (inv: Invite) => ({ name: inv.name, limit: inv.limit, used: inv.used, expiresAt: inv.expiresAt });

export async function consume(kv: KVNamespace, hash: string, invite: Invite, field: "used" | "letters", delta = 1) {
  const fresh = (await kv.get<Invite>(PREFIX + hash, "json")) ?? invite;
  const next = { ...fresh, [field]: Math.max(0, fresh[field] + delta), lastUsedAt: new Date().toISOString() };
  await save(kv, hash, next);
  return next;
}

// ---- admin -----------------------------------------------------------------------------------------------------

async function safeEqual(a: string, b: string): Promise<boolean> {
  const [x, y] = await Promise.all([sha256Hex(a), sha256Hex(b)]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x.charCodeAt(i) ^ y.charCodeAt(i);
  return diff === 0;
}

export async function isAdmin(request: Request, adminKey: string | undefined): Promise<boolean> {
  const given = request.headers.get("X-Admin-Key") ?? "";
  return Boolean(adminKey && adminKey.length >= 24 && given && (await safeEqual(given, adminKey)));
}

async function listAll(kv: KVNamespace): Promise<{ hash: string; invite: Invite }[]> {
  const out: { hash: string; invite: Invite }[] = [];
  let cursor: string | undefined;
  do {
    const page = await kv.list<Invite>({ prefix: PREFIX, cursor });
    for (const k of page.keys) {
      const invite = k.metadata ?? (await kv.get<Invite>(k.name, "json"));
      if (invite) out.push({ hash: k.name.slice(PREFIX.length), invite });
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out.sort((a, b) => a.invite.createdAt.localeCompare(b.invite.createdAt));
}

async function findById(kv: KVNamespace, id: string) {
  const all = await listAll(kv);
  return all.find((x) => x.invite.id === id) ?? null;
}

export async function handleAdmin(request: Request, kv: KVNamespace, path: string): Promise<Response> {
  const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  const body = request.method === "POST" ? ((await request.json().catch(() => ({}))) as Record<string, unknown>) : {};

  if (request.method === "GET" && path === "/api/admin/invites") return json({ invites: (await listAll(kv)).map((x) => x.invite) });

  if (request.method === "POST" && path === "/api/admin/invites") {
    const name = String(body.name ?? "").trim().slice(0, 120);
    const limit = Number(body.limit ?? 10);
    const days = Number(body.days ?? 30);
    if (!name || !Number.isInteger(limit) || limit < 1 || limit > 1000 || !Number.isInteger(days) || days < 1 || days > 366) {
      return json({ error: "bad_request" }, 400);
    }
    const token = newToken();
    const hash = await sha256Hex(token);
    const now = new Date();
    const invite: Invite = {
      id: hash.slice(0, 10), name, limit, used: 0, letters: 0, revoked: false,
      createdAt: now.toISOString(), expiresAt: new Date(now.getTime() + days * 86_400_000).toISOString(),
    };
    await save(kv, hash, invite);
    return json({ token, invite }, 201);
  }

  const m = /^\/api\/admin\/invites\/([0-9a-f]{10})\/(topup|revoke|extend)$/.exec(path);
  if (request.method === "POST" && m) {
    const found = await findById(kv, m[1]);
    if (!found) return json({ error: "not_found" }, 404);
    const inv = { ...found.invite };
    if (m[2] === "revoke") inv.revoked = true;
    if (m[2] === "topup") {
      const add = Number(body.add ?? 0);
      if (!Number.isInteger(add) || add < 1 || add > 1000) return json({ error: "bad_request" }, 400);
      inv.limit += add;
    }
    if (m[2] === "extend") {
      const days = Number(body.days ?? 0);
      if (!Number.isInteger(days) || days < 1 || days > 366) return json({ error: "bad_request" }, 400);
      const from = Math.max(Date.now(), Date.parse(inv.expiresAt));
      inv.expiresAt = new Date(from + days * 86_400_000).toISOString();
    }
    await save(kv, found.hash, inv);
    return json({ invite: inv });
  }
  return json({ error: "not_found" }, 404);
}
