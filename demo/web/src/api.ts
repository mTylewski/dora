// Calls to the analysis server. Only anonymized text (and anonymized letter facts) is ever sent.
import { currentToken } from "./invite";

const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8787";

export interface InviteInfo { name: string; limit: number; used: number; expiresAt: string }
/** null: invitations are not required (local development). */
export type InviteState = { ok: true; invite: InviteInfo | null } | { ok: false; code: string };

const headers = (): Record<string, string> => {
  const token = currentToken();
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
};

let inviteCache: Promise<InviteState> | null = null;
const announce = (invite: InviteInfo | null | undefined) => {
  if (invite) inviteCache = Promise.resolve({ ok: true, invite });
  window.dispatchEvent(new Event("dora-invite"));
};

/** Status of this browser's invitation (cached; refreshed after each analysis). */
export function inviteState(refresh = false): Promise<InviteState> {
  if (!inviteCache || refresh) {
    inviteCache = fetch(`${API}/api/invite`, { headers: headers() })
      .then(async (res) => {
        const body = (await res.json().catch(() => ({}))) as { invite?: InviteInfo | null; error?: string };
        return res.ok ? { ok: true as const, invite: body.invite ?? null } : { ok: false as const, code: body.error ?? `http_${res.status}` };
      })
      .catch(() => ({ ok: false as const, code: "offline" }));
  }
  return inviteCache;
}

export interface AnalysisResult {
  classification: { document_id: string; type: string }[];
  extraction: unknown;
  clauses: unknown[];
}

const STEP_LABELS: Record<string, string> = {
  classify: "Rozpoznawanie rodzaju dokumentów",
  extract_and_clauses: "Ekstrakcja danych z cytatami i ocena klauzul (zwykle 30–90 s)",
  one_of_two: "Kończenie analizy",
  finishing: "Przygotowanie wyników",
};

export class ApiError extends Error {}

export async function analyzeText(documents: { id: string; pages: string[] }[], onProgress: (label: string, pct: number) => void): Promise<AnalysisResult> {
  const res = await fetch(`${API}/api/analyze`, { method: "POST", headers: headers(), body: JSON.stringify({ documents }) });
  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    if (body.error?.startsWith("invite_")) { inviteCache = null; announce(null); }
    throw new ApiError(body.error ?? `http_${res.status}`);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let result: AnalysisResult | null = null;
  let error: string | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let nl;
    while ((nl = buffer.indexOf("\n")) !== -1) {
      const line = JSON.parse(buffer.slice(0, nl));
      buffer = buffer.slice(nl + 1);
      if (line.type === "progress") onProgress(STEP_LABELS[line.step] ?? "Analiza", line.pct);
      if (line.type === "result") result = line;
      if (line.type === "error") error = line.code;
      if (line.type === "result" || line.type === "error") announce(line.invite);
    }
  }
  if (error || !result) throw new ApiError(error ?? "no_result");
  return result;
}

export async function requestJustification(facts: unknown): Promise<string> {
  const res = await fetch(`${API}/api/justification`, { method: "POST", headers: headers(), body: JSON.stringify({ facts }) });
  const body = (await res.json()) as { error?: string; justification: string };
  if (!res.ok) throw new ApiError(body.error ?? `http_${res.status}`);
  return body.justification;
}
