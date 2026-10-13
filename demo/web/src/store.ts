// Data kept on the lawyer's computer (encrypted in the vault): firm, lawyers, templates and cases.
import type { Person } from "../../shared/anonymize";
import type { Correction } from "../../shared/corrections";
import type { Row } from "../../shared/letter";
import type { ClauseFlag, Extraction } from "../../shared/schema";
import type { Profile, Vault } from "./vault";

let vault: Vault | null = null;
export const setVault = (v: Vault | null) => { vault = v; };
export function v(): Vault {
  if (!vault) throw new Error("locked");
  return vault;
}

export interface FirmSettings {
  name: string; address: string; city: string; bankAccount: string;
  paymentDeadlineDays: number; caseNumberPattern: string; legalBasis: string;
}
export interface Lawyer { id: string; fullName: string; title: string; registryNo: string; active: boolean }
export interface TemplateMeta { id: string; name: string; description: string; createdAt: string }
export interface CaseDoc { id: string; name: string; ocrPages: number[]; pages: string[]; anon: string[] }
export interface LetterDraft {
  templateId: string; templateName: string; values: Record<string, string>; rows: Row[];
  totalGrosze: string; capped: boolean; preparedAt: string; savedAt?: string; warnings: string[];
}
export interface CaseRecord {
  id: string; title: string; caseNumber: string; lawyerId: string; createdAt: string; asOf: string;
  status: "analyzing" | "ready" | "error"; errorCode?: string;
  documents: CaseDoc[];
  mapping: [string, string][];
  persons: Person[];
  replacements: { token: string; label: string; original: string }[];
  analysis: { extraction: Extraction; clauses: ClauseFlag[]; classification: { document_id: string; type: string }[] } | null;
  corrections: [string, Correction][];
  letterForm?: Record<string, unknown>;
  letter?: LetterDraft;
}

export const DEFAULT_TEMPLATE_ID = "default";
export const DEFAULT_TEMPLATE: TemplateMeta = {
  id: DEFAULT_TEMPLATE_ID, name: "Wezwanie przedsądowe do zapłaty (szablon domyślny)",
  description: "Szablon dostarczony z programem — punkt wyjścia do przygotowania własnego.", createdAt: "",
};

const DEFAULT_FIRM: FirmSettings = {
  name: "", address: "", city: "", bankAccount: "", paymentDeadlineDays: 14, caseNumberPattern: "KAN/{rok}/{nr}", legalBasis: "",
};

export async function getProfile(): Promise<Profile & { lawyerId?: string }> {
  return (await v().get("profile", "me")) ?? { name: "", email: "" };
}
export const saveProfile = (p: Profile & { lawyerId?: string }) => v().put("profile", "me", p);

export async function getFirm(): Promise<FirmSettings> {
  return { ...DEFAULT_FIRM, ...((await v().get<FirmSettings>("settings", "firm")) ?? {}) };
}
export const saveFirm = (f: FirmSettings) => v().put("settings", "firm", f);

export async function listLawyers(): Promise<Lawyer[]> {
  return (await v().list<Lawyer>("lawyer")).map((r) => r.value).sort((a, b) => a.fullName.localeCompare(b.fullName, "pl"));
}
export const saveLawyer = (l: Lawyer) => v().put("lawyer", l.id, l);

export async function listTemplates(): Promise<TemplateMeta[]> {
  const own = (await v().list<TemplateMeta>("template")).map((r) => r.value).sort((a, b) => a.name.localeCompare(b.name, "pl"));
  return [DEFAULT_TEMPLATE, ...own];
}
export async function templateBytes(id: string): Promise<ArrayBuffer> {
  if (id === DEFAULT_TEMPLATE_ID) return (await fetch("/templates/domyslny.docx")).arrayBuffer();
  const bytes = await v().getBytes("template-file", id);
  if (!bytes) throw new Error("Brak pliku szablonu.");
  return bytes.slice().buffer;
}
export async function saveTemplate(meta: TemplateMeta, bytes: Uint8Array<ArrayBuffer>) {
  await v().putBytes("template-file", meta.id, bytes);
  await v().put("template", meta.id, meta);
}
export async function deleteTemplate(id: string) {
  await v().delete("template", id);
  await v().delete("template-file", id);
}

export async function listCases(): Promise<CaseRecord[]> {
  return (await v().list<CaseRecord>("case")).map((r) => r.value).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
export const getCase = (id: string) => v().get<CaseRecord>("case", id);
export const saveCase = (c: CaseRecord) => v().put("case", c.id, c);
export async function deleteCase(id: string) {
  await v().delete("case", id);
  await v().deletePrefix("case-pdf", `${id}/`);
}
export const saveCasePdf = (caseId: string, docId: string, bytes: Uint8Array<ArrayBuffer>) => v().putBytes("case-pdf", `${caseId}/${docId}`, bytes);
export const getCasePdf = (caseId: string, docId: string) => v().getBytes("case-pdf", `${caseId}/${docId}`);

/** Next number for a pattern like KAN/{rok}/{nr} (numbering restarts every year). */
export function nextCaseNumber(pattern: string, existing: string[], today = new Date()): string {
  let p = pattern || "KAN/{rok}/{nr}";
  if (!p.includes("{nr}")) p += "/{nr}";
  const year = String(today.getFullYear());
  const escaped = p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace("\\{rok\\}", year).replace("\\{nr\\}", "(\\d+)");
  const re = new RegExp(`^${escaped}$`);
  const used = existing.map((n) => re.exec(n)).filter(Boolean).map((m) => Number(m![1]));
  return p.replace("{rok}", year).replace("{nr}", String(Math.max(0, ...used) + 1).padStart(3, "0"));
}
