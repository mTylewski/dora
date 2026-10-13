// Invitation link (#/z/<token>): the token is remembered in this browser and sent with each analysis request.
// It is only an access ticket for the hosted demo; it unlocks no data (cases stay encrypted locally).
const KEY = "dora-invite";
let memory: string | null = null;

export function inviteToken(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

/** Reads the token from an invitation link, stores it and removes it from the address bar. Returns true if found. */
export function captureInvite(): boolean {
  const m = /^#\/z\/([A-Za-z0-9_-]{16,64})$/.exec(location.hash);
  if (!m) return false;
  try { localStorage.setItem(KEY, m[1]); } catch { /* private mode: token lives only for this visit */ memory = m[1]; }
  history.replaceState(null, "", location.pathname + location.search + "#/cases");
  return true;
}

export const currentToken = () => inviteToken() ?? memory;
