import { readFileSync } from "node:fs";
import { join } from "node:path";
import JSZip from "jszip";
import { DOMParser, XMLSerializer } from "@xmldom/xmldom";
import { describe, expect, it } from "vitest";

// Browsers provide DOMParser/XMLSerializer; in Node the tests use xmldom (same standard API).
Object.assign(globalThis, { DOMParser, XMLSerializer });
import { checkTemplate, fillTemplate, templatePlaceholders } from "./docx";

const template = readFileSync(join(process.cwd(), "..", "templates", "wezwanie_do_zaplaty.docx"));

async function text(blob: Blob): Promise<string> {
  const zip = await JSZip.loadAsync(await blob.arrayBuffer());
  return (await zip.file("word/document.xml")!.async("string")).replace(/<[^>]+>/g, " ");
}

describe("docx templates in the browser", () => {
  it("reads placeholders of the default template and accepts it", async () => {
    const found = await templatePlaceholders(template);
    expect(found.has("justification") && found.has("penalty_rows") && found.has("case_number")).toBe(true);
    const check = await checkTemplate(template);
    expect(check.errors).toEqual([]);
    expect(check.warnings).toEqual([]);
  });

  it("fills values, splits paragraphs and repeats the table row", async () => {
    const blob = await fillTemplate(template, {
      case_number: "KAN/2026/001", justification: "Pierwszy akapit.\n\nDrugi akapit.", demand: "wzywam do zapłaty",
    }, [["Opóźnienie A", "01.07.2026 – 01.09.2026", "63", "6 804,00 zł"], ["Opóźnienie B", "x", "1", "1,00 zł"]]);
    const t = await text(blob);
    expect(t).toContain("Sygn.: KAN/2026/001");
    expect(t).toContain("Pierwszy akapit.");
    expect(t).toContain("Drugi akapit.");
    expect(t).toContain("6 804,00 zł");
    expect(t).toContain("Opóźnienie B");
    expect(t).not.toContain("{{penalty_rows}}");
  });

  it("rejects files that are not templates", async () => {
    expect((await checkTemplate(new Uint8Array([1, 2, 3]))).errors[0]).toContain("nie jest poprawnym");
  });
});
