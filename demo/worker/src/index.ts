// Cloudflare Worker - hosted service with browser-side anonymization.
// The browser reads the PDFs (text layer / local OCR), anonymizes them and shows the lawyer what will be sent.
// This Worker receives ONLY the approved anonymized text: no PDF, no images, no mapping of tokens to people.
// It runs the same fixed pipeline as the MVP (classify -> extract + clauses) and returns structured results;
// quotes are verified, amounts calculated and personal data restored in the browser.
// The API key exists only as a Worker secret (wrangler secret put ANTHROPIC_API_KEY).
// Logs: step, timing, tokens, error code. Never document content.
import Anthropic from "@anthropic-ai/sdk";
import type { BetaContentBlockParam, BetaMessageParam } from "@anthropic-ai/sdk/resources/beta/messages/messages";
import { z } from "zod";
import classifySystem from "../../../prompts/classify_system.md";
import clausesSystemTemplate from "../../../prompts/clauses_system.md";
import extractSystem from "../../../prompts/extract_system.md";
import letterSystem from "../../../prompts/letter_system.md";
import classificationSchema from "../../../schemas/classification_output.json";
import clausesSchema from "../../../schemas/clauses_output.json";
import extractionSchema from "../../../schemas/extraction_model_output.json";
import justificationSchema from "../../../schemas/justification_output.json";
import { Anonymizer } from "../../shared/anonymize";
import library from "../../shared/generated/clause_library.json";
import config from "../../shared/generated/config.json";
import { Classification, ClauseFlags, Extraction, Justification } from "../../shared/schema";
import { type Invite, type InviteStatus, bearer, consume, handleAdmin, inviteStatus, isAdmin, loadInvite, publicView } from "./invites";

export interface Env {
  ANTHROPIC_API_KEY: string;
  ALLOWED_ORIGINS: string; // comma-separated
  MAX_DOCUMENTS?: string;
  MAX_TOTAL_CHARS?: string;
  REFUSAL_FALLBACK?: string; // "false" to disable
  MODEL_CLASSIFY?: string;
  MODEL_EXTRACT?: string;
  MODEL_CLAUSES?: string;
  MODEL_LETTER?: string;
  INVITES?: KVNamespace; // invitation links (see invites.ts)
  INVITES_REQUIRED?: string; // "false" only for local development
  ADMIN_KEY?: string; // secret for scripts/invite.mjs
}

type StepName = "classify" | "extract" | "clauses" | "letter";
const FALLBACK_BETA = "server-side-fallback-2026-07-01";
const CLASSIFY_PAGES = 3;
const clausesSystem = clausesSystemTemplate.replace("{library}", library.rendered);
const knownClauseIds = new Set(library.patterns.map((p) => p.id));
// Identifiers that must never reach the model; their presence means the text was not anonymized.
const GUARDED_LABELS = new Set(["PESEL", "KONTO", "DOWOD", "EMAIL", "TELEFON", "KW", "NIP", "REGON"]);

class StepError extends Error {
  constructor(public code: string) { super(code); }
}

const AnalyzeRequest = z.object({
  documents: z.array(z.object({
    id: z.string().regex(/^doc_\d{1,2}$/),
    pages: z.array(z.string()).min(1).max(400),
  })).min(1),
}).strict();
const JustificationRequest = z.object({ facts: z.record(z.string(), z.unknown()) });

type Doc = z.infer<typeof AnalyzeRequest>["documents"][number] & { type?: string };

function settings(step: StepName, env: Env) {
  const base = config.models[step] as { model: string; max_tokens: number; effort?: string; refusal_fallback?: boolean };
  const override = { classify: env.MODEL_CLASSIFY, extract: env.MODEL_EXTRACT, clauses: env.MODEL_CLAUSES, letter: env.MODEL_LETTER }[step];
  return {
    model: override || base.model,
    maxTokens: base.max_tokens,
    effort: base.effort as "low" | "medium" | "high" | "xhigh" | "max" | undefined,
    fallback: !!base.refusal_fallback && env.REFUSAL_FALLBACK !== "false",
  };
}

/** Same layout as pipeline/documents.py render_document, so prompts behave identically. */
export function renderDocument(doc: Doc, maxPages?: number): string {
  const pages = maxPages ? doc.pages.slice(0, maxPages) : doc.pages;
  const typeAttr = doc.type ? ` type="${doc.type}"` : "";
  const body = pages.map((text, i) => `<page number="${i + 1}">\n${text}\n</page>`).join("\n");
  return `<document id="${doc.id}"${typeAttr}>\n${body}\n</document>`;
}

/** Labels of identifiers found in supposedly anonymized text (defense in depth). */
export function residualIdentifiers(docs: Doc[]): string[] {
  const probe = new Anonymizer();
  for (const doc of docs) for (const page of doc.pages) probe.anonymize(page);
  return [...new Set(probe.replacements.map((r) => r.label).filter((l) => GUARDED_LABELS.has(l)))].sort();
}

/** One structured call with one retry on invalid output (CLAUDE.md, section 3, rule 5). */
async function callStructured<T>(
  client: Anthropic, env: Env, step: StepName, system: string, content: BetaContentBlockParam[],
  schema: object, parser: z.ZodType<T>,
): Promise<T> {
  const s = settings(step, env);
  let messages: BetaMessageParam[] = [{ role: "user", content }];
  let lastError = "";
  for (const attempt of [1, 2]) {
    const started = Date.now();
    const stream = client.beta.messages.stream({
      model: s.model,
      max_tokens: s.maxTokens,
      system: [{ type: "text", text: system, cache_control: { type: "ephemeral" } }],
      messages,
      output_config: { format: { type: "json_schema", schema: schema as Record<string, unknown> }, ...(s.effort ? { effort: s.effort } : {}) },
      ...(s.fallback ? { betas: [FALLBACK_BETA], fallbacks: "default" as const } : {}),
    });
    let message;
    try {
      message = await stream.finalMessage();
    } catch (err) {
      const status = err instanceof Anthropic.APIError ? err.status : undefined;
      console.log(JSON.stringify({ step, attempt, error: "api_error", status }));
      throw new StepError(status === 429 ? "rate_limited" : "api_error");
    }
    console.log(JSON.stringify({
      step, attempt, model: s.model, ms: Date.now() - started, stop: message.stop_reason,
      in: message.usage.input_tokens, out: message.usage.output_tokens,
      cache_read: message.usage.cache_read_input_tokens,
    }));
    if (message.stop_reason === "refusal") throw new StepError("refusal");
    const text = message.content.find((b) => b.type === "text")?.text ?? "";
    if (message.stop_reason === "max_tokens") {
      lastError = "output truncated (max_tokens)";
    } else {
      try {
        const parsed = parser.safeParse(JSON.parse(text));
        if (parsed.success) return parsed.data;
        lastError = parsed.error.issues.slice(0, 10).map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
      } catch {
        lastError = "invalid JSON";
      }
    }
    messages = [
      ...messages,
      { role: "assistant", content: message.content as BetaContentBlockParam[] },
      { role: "user", content: [{ type: "text", text: `The previous answer was rejected by validation: ${lastError}. Return the complete corrected JSON only.` }] },
    ];
  }
  throw new StepError("invalid_output");
}

function cors(request: Request, env: Env): Record<string, string> {
  const origin = request.headers.get("Origin") ?? "";
  const allowed = env.ALLOWED_ORIGINS.split(",").map((o) => o.trim());
  return allowed.includes(origin)
    ? { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization", "Access-Control-Max-Age": "86400", Vary: "Origin" }
    : {};
}

const json = (data: unknown, status: number, headers: Record<string, string>) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json" } });

type Grant = { hash: string; invite: Invite } | null; // null = invites disabled (local development)
type Check = { ok: true; grant: Grant } | { ok: false; response: Response };

/** Checks the invitation token sent by the browser (Authorization: Bearer <token>). */
async function checkInvite(request: Request, env: Env, headers: Record<string, string>, forAnalysis: boolean): Promise<Check> {
  if (env.INVITES_REQUIRED === "false") return { ok: true, grant: null };
  if (!env.INVITES) return { ok: false, response: json({ error: "invites_unavailable" }, 503, headers) };
  const token = bearer(request);
  const found = await loadInvite(env.INVITES, token);
  const status: InviteStatus = token ? inviteStatus(found?.invite ?? null, new Date(), forAnalysis) : "invite_missing";
  if (status !== "ok") {
    console.log(JSON.stringify({ step: "invite", error: status }));
    return { ok: false, response: json({ error: status }, status === "invite_missing" || status === "invite_invalid" ? 401 : 403, headers) };
  }
  return { ok: true, grant: found };
}

async function analyze(request: Request, env: Env, ctx: ExecutionContext, headers: Record<string, string>) {
  const check = await checkInvite(request, env, headers, true);
  if (!check.ok) return check.response;
  const grant = check.grant;
  const raw = await request.text();
  const maxChars = Number(env.MAX_TOTAL_CHARS ?? 1_500_000);
  if (raw.length > maxChars) return json({ error: "too_large" }, 413, headers);
  const parsed = AnalyzeRequest.safeParse((() => { try { return JSON.parse(raw); } catch { return null; } })());
  if (!parsed.success) return json({ error: "bad_request" }, 400, headers);
  const docs: Doc[] = parsed.data.documents;
  if (docs.length > Number(env.MAX_DOCUMENTS ?? 10)) return json({ error: "too_large" }, 413, headers);
  const residual = residualIdentifiers(docs);
  if (residual.length) {
    console.log(JSON.stringify({ step: "guard", error: "pii_detected", labels: residual }));
    return json({ error: "pii_detected", labels: residual }, 422, headers);
  }
  // The analysis is counted when it starts and refunded if it fails on our side.
  let invite = grant ? await consume(env.INVITES!, grant.hash, grant.invite, "used") : null;

  // NDJSON stream: progress lines keep the connection alive during the model calls.
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();
  const send = (obj: unknown) => writer.write(encoder.encode(JSON.stringify(obj) + "\n"));

  const work = (async () => {
    const keepAlive = setInterval(() => void send({ type: "keepalive" }), 10_000);
    try {
      const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
      await send({ type: "progress", step: "classify", pct: 10 });
      const classification = await callStructured(client, env, "classify", classifySystem,
        [{ type: "text", text: docs.map((d) => renderDocument(d, CLASSIFY_PAGES)).join("\n\n") }],
        classificationSchema, Classification);
      const types = new Map(classification.documents.map((c) => [c.document_id, c.type]));
      for (const d of docs) d.type = types.get(d.id) ?? "other";

      const content: BetaContentBlockParam[] = docs.map((d) => ({ type: "text", text: renderDocument(d) }));
      await send({ type: "progress", step: "extract_and_clauses", pct: 25 });
      let done = 0;
      const tick = async () => { done += 1; await send({ type: "progress", step: done === 1 ? "one_of_two" : "finishing", pct: done === 1 ? 65 : 95 }); };
      const [extraction, clauses] = await Promise.all([
        callStructured(client, env, "extract", extractSystem,
          [...content, { type: "text", text: "Extract the case card from the documents above." }],
          extractionSchema, Extraction).then(async (r) => { await tick(); return r; }),
        callStructured(client, env, "clauses", clausesSystem,
          [...content, { type: "text", text: "Flag the clauses that match the pattern library." }],
          clausesSchema, ClauseFlags).then(async (r) => { await tick(); return r; }),
      ]);
      const flags = clauses.flags.filter((f) => knownClauseIds.has(f.clause_id));
      await send({
        type: "result", classification: classification.documents, extraction, clauses: flags,
        dropped_unknown_ids: clauses.flags.length - flags.length, invite: invite ? publicView(invite) : null,
      });
    } catch (err) {
      const code = err instanceof StepError ? err.code : "internal_error";
      if (!(err instanceof StepError)) console.log(JSON.stringify({ step: "analyze", error: "internal_error" }));
      if (grant) invite = await consume(env.INVITES!, grant.hash, grant.invite, "used", -1).catch(() => invite);
      await send({ type: "error", code, invite: invite ? publicView(invite) : null });
    } finally {
      clearInterval(keepAlive);
      await writer.close();
    }
  })();
  ctx.waitUntil(work);
  return new Response(readable, { headers: { ...headers, "Content-Type": "application/x-ndjson", "Cache-Control": "no-store" } });
}

async function justification(request: Request, env: Env, headers: Record<string, string>) {
  const check = await checkInvite(request, env, headers, false);
  if (!check.ok) return check.response;
  const raw = await request.text();
  if (raw.length > 20_000) return json({ error: "too_large" }, 413, headers);
  const parsed = JustificationRequest.safeParse((() => { try { return JSON.parse(raw); } catch { return null; } })());
  if (!parsed.success) return json({ error: "bad_request" }, 400, headers);
  if (residualIdentifiers([{ id: "doc_1", pages: [JSON.stringify(parsed.data.facts)] }]).length) {
    return json({ error: "pii_detected" }, 422, headers);
  }
  try {
    const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
    if (check.grant) await consume(env.INVITES!, check.grant.hash, check.grant.invite, "letters");
    const result = await callStructured(client, env, "letter", letterSystem,
      [{ type: "text", text: JSON.stringify(parsed.data.facts, null, 2) }], justificationSchema, Justification);
    return json(result, 200, headers);
  } catch (err) {
    return json({ error: err instanceof StepError ? err.code : "internal_error" }, 502, headers);
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/admin/")) {
      if (!env.INVITES) return json({ error: "invites_unavailable" }, 503, {});
      if (!(await isAdmin(request, env.ADMIN_KEY))) return json({ error: "unauthorized" }, 401, {});
      return handleAdmin(request, env.INVITES, url.pathname);
    }
    const headers = cors(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: headers["Access-Control-Allow-Origin"] ? 204 : 403, headers });
    if (!headers["Access-Control-Allow-Origin"]) return json({ error: "forbidden_origin" }, 403, {});
    if (request.method === "POST" && url.pathname === "/api/analyze") return analyze(request, env, ctx, headers);
    if (request.method === "POST" && url.pathname === "/api/justification") return justification(request, env, headers);
    if (request.method === "GET" && url.pathname === "/api/invite") {
      const check = await checkInvite(request, env, headers, false);
      if (!check.ok) return check.response;
      return json({ invite: check.grant ? publicView(check.grant.invite) : null }, 200, headers);
    }
    return json({ error: "not_found" }, 404, headers);
  },
} satisfies ExportedHandler<Env>;
