// Fill .docx templates in the browser - port of pipeline/letter.py render_letter / check_template.
// Placeholders {{name}} may sit anywhere in a paragraph (body, tables, headers, footers); a paragraph containing a
// placeholder is rewritten with the formatting of its first run. The table row with {{penalty_rows}} is repeated once
// per calculation row. Values with blank lines become separate paragraphs; single line breaks become <w:br/>.
import JSZip from "jszip";
import { PLACEHOLDERS, type Row, TABLE_PLACEHOLDER } from "../../shared/letter";

const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const PLACEHOLDER = /\{\{(\w+)\}\}/g;
const PARTS = /^word\/(document|header\d*|footer\d*)\.xml$/;

function paragraphText(p: Element): string {
  return [...p.getElementsByTagNameNS(W, "t")].map((t) => t.textContent ?? "").join("");
}

function setParagraphText(p: Element, text: string): void {
  const doc = p.ownerDocument;
  const runs = [...p.getElementsByTagNameNS(W, "r")];
  let run = runs[0];
  if (!run) {
    run = doc.createElementNS(W, "w:r");
    p.appendChild(run);
  }
  for (const r of runs.slice(1)) r.parentNode?.removeChild(r);
  for (const child of [...run.childNodes]) {
    const name = (child as Element).localName;
    if (name === "t" || name === "br" || name === "tab") run.removeChild(child);
  }
  text.split("\n").forEach((line, i) => {
    if (i > 0) run.appendChild(doc.createElementNS(W, "w:br"));
    const t = doc.createElementNS(W, "w:t");
    t.setAttributeNS("http://www.w3.org/XML/1998/namespace", "xml:space", "preserve");
    t.textContent = line;
    run.appendChild(t);
  });
}

function fillParagraph(p: Element, values: Record<string, string>): void {
  const text = paragraphText(p);
  if (!text.includes("{{")) return;
  const filled = text.replace(PLACEHOLDER, (m, name: string) => values[name] ?? m);
  const chunks = filled.includes("\n\n") ? filled.split(/\n\s*\n/).map((c) => c.trim()) : [filled];
  setParagraphText(p, chunks[0]);
  let anchor: Element = p;
  for (const chunk of chunks.slice(1)) {
    const copy = p.cloneNode(true) as Element;
    anchor.parentNode!.insertBefore(copy, anchor.nextSibling);
    setParagraphText(copy, chunk);
    anchor = copy;
  }
}

function fillTables(doc: Document, rows: Row[]): void {
  for (const tr of [...doc.getElementsByTagNameNS(W, "tr")]) {
    if (!paragraphText(tr).includes(`{{${TABLE_PLACEHOLDER}}}`)) continue;
    for (const data of rows) {
      const copy = tr.cloneNode(true) as Element;
      const cells = [...copy.getElementsByTagNameNS(W, "tc")];
      cells.forEach((tc, i) => {
        const p = tc.getElementsByTagNameNS(W, "p")[0];
        if (p) setParagraphText(p, data[i] ?? "");
      });
      tr.parentNode!.insertBefore(copy, tr);
    }
    tr.parentNode!.removeChild(tr);
  }
}

export async function fillTemplate(template: ArrayBuffer | Uint8Array, values: Record<string, string>, rows: Row[]): Promise<Blob> {
  const zip = await JSZip.loadAsync(template);
  for (const name of Object.keys(zip.files).filter((n) => PARTS.test(n))) {
    const xml = await zip.file(name)!.async("string");
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    if (name === "word/document.xml") fillTables(doc, rows);
    for (const p of [...doc.getElementsByTagNameNS(W, "p")]) fillParagraph(p, values);
    zip.file(name, new XMLSerializer().serializeToString(doc));
  }
  return zip.generateAsync({ type: "blob", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
}

export async function templatePlaceholders(template: ArrayBuffer | Uint8Array): Promise<Set<string>> {
  const zip = await JSZip.loadAsync(template);
  const found = new Set<string>();
  for (const name of Object.keys(zip.files).filter((n) => PARTS.test(n))) {
    const doc = new DOMParser().parseFromString(await zip.file(name)!.async("string"), "application/xml");
    for (const p of [...doc.getElementsByTagNameNS(W, "p")]) {
      for (const m of paragraphText(p).matchAll(PLACEHOLDER)) found.add(m[1]);
    }
  }
  return found;
}

/** Same rules as pipeline/letter.py check_template. */
export async function checkTemplate(template: ArrayBuffer | Uint8Array): Promise<{ errors: string[]; warnings: string[]; found: Set<string> }> {
  let found: Set<string>;
  try {
    found = await templatePlaceholders(template);
  } catch {
    return { errors: ["Plik nie jest poprawnym dokumentem .docx."], warnings: [], found: new Set() };
  }
  const known = new Set([...Object.keys(PLACEHOLDERS), TABLE_PLACEHOLDER]);
  const errors = [...found].some((f) => known.has(f)) ? [] : ["Szablon nie zawiera żadnego pola {{...}} — system nie miałby czego uzupełnić."];
  const warnings = [...found].filter((f) => !known.has(f)).sort().map((f) => `Nieznane pole {{${f}}} — zostanie w piśmie bez zmian.`);
  if (!found.has(TABLE_PLACEHOLDER)) warnings.push("Szablon nie ma tabeli z polem {{penalty_rows}} — wyliczenie nie pojawi się w tabeli.");
  if (!found.has("justification")) warnings.push("Szablon nie ma pola {{justification}} — projekt uzasadnienia nie będzie przygotowywany.");
  return { errors, warnings, found };
}
