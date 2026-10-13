// Quote verification - TypeScript port of pipeline/verify_quotes.py (same rules, same issue codes).
import { iterFields, type Extraction, type FieldT } from "./schema";

const CHAR_MAP: Record<string, string> = {
  "„": '"', "”": '"', "“": '"', "«": '"', "»": '"',
  "‘": "'", "’": "'", "‚": "'",
  "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
  " ": " ", " ": " ", " ": " ",
};
const CHAR_RE = new RegExp(`[${Object.keys(CHAR_MAP).join("")}]`, "g");
const LINE_BREAK_HYPHEN = /([\p{L}\p{N}_])-\s*\n\s*([\p{L}\p{N}_])/gu;

export type Issue =
  | "quote_missing" | "quote_not_found" | "page_mismatch" | "page_missing"
  | "unknown_document" | "low_confidence" | "value_unresolved";

export interface QuoteIssue { path: string; issue: Issue; found_page?: number }

export function normalize(text: string, joinHyphenation = false): string {
  let t = text.normalize("NFKC").replace(/­/g, "");
  if (joinHyphenation) t = t.replace(LINE_BREAK_HYPHEN, "$1$2");
  t = t.replace(CHAR_RE, (c) => CHAR_MAP[c]);
  return t.replace(/\s+/g, " ").trim();
}

export class DocumentText {
  private variants: string[][];
  constructor(public pages: string[]) {
    this.variants = [false, true].map((j) => pages.map((p) => normalize(p, j)));
  }

  /** 1-based pages where the quote starts (also across a page break). */
  find(quote: string): number[] {
    for (const [idx, pages] of this.variants.entries()) {
      const q = normalize(quote, idx === 1);
      if (!q) return [];
      const hits: number[] = [];
      pages.forEach((page, i) => {
        const window = i + 1 === pages.length ? page : `${page} ${pages[i + 1]}`;
        const pos = window.indexOf(q);
        if (pos !== -1 && pos < page.length && !hits.includes(i + 1)) hits.push(i + 1);
      });
      if (hits.length) return hits;
    }
    return [];
  }
}

export function verifyField(path: string, f: FieldT, docs: Map<string, DocumentText>): QuoteIssue[] {
  const issues: QuoteIssue[] = [];
  if (f.value === null && f.quote === null) return issues;
  if (!f.quote) {
    issues.push({ path, issue: "quote_missing" });
  } else {
    let doc = docs.get(f.document_id ?? "");
    if (!doc && docs.size === 1 && f.document_id === null) doc = [...docs.values()][0];
    if (!doc) issues.push({ path, issue: "unknown_document" });
    else {
      const pages = doc.find(f.quote);
      if (!pages.length) issues.push({ path, issue: "quote_not_found" });
      else if (f.page === null) issues.push({ path, issue: "page_missing", found_page: pages[0] });
      else if (!pages.includes(f.page)) issues.push({ path, issue: "page_mismatch", found_page: pages[0] });
    }
  }
  if (f.value === null) issues.push({ path, issue: "value_unresolved" });
  if (f.confidence === "low") issues.push({ path, issue: "low_confidence" });
  return issues;
}

/** Returns issues and the set of paths needing review. Documents with no text layer cannot be verified. */
export function verifyExtraction(ex: Extraction, documents: Map<string, string[]>) {
  const docs = new Map([...documents].map(([id, pages]) => [id, new DocumentText(pages)]));
  const issues: QuoteIssue[] = [];
  const needsReview = new Set<string>();
  for (const [path, f] of iterFields(ex)) {
    const found = verifyField(path, f, docs);
    if (found.length) needsReview.add(path);
    issues.push(...found);
  }
  return { issues, needsReview };
}

/** Quote check for clause flags (same rules as pipeline/clauses.py). */
export function verifyClauseQuote(
  quote: string, page: number | null, documentId: string | null, documents: Map<string, string[]>,
): Issue | null {
  let pages = documents.get(documentId ?? "");
  if (!pages && documents.size === 1 && documentId === null) pages = [...documents.values()][0];
  if (!pages) return "unknown_document";
  const found = new DocumentText(pages).find(quote);
  if (!found.length) return "quote_not_found";
  if (page === null || !found.includes(page)) return "page_mismatch";
  return null;
}
