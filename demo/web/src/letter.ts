// Demand letter draft (.docx) generated in the browser with the `docx` library.
// Same structure and wording as templates/wezwanie_do_zaplaty.docx in the MVP.
import { AlignmentType, Document, Packer, Paragraph, Table, TableCell, TableRow, TextRun, WidthType } from "docx";
import { EVENT_LABELS, type PenaltyResult, fmtDate, formatPln } from "../../shared/calculator";
import { demanded } from "../../shared/adapter";
import config from "../../shared/generated/config.json";

export interface Parties {
  firmName: string; firmCity: string; lawyer: string;
  clientName: string; clientAddress: string;
  developerName: string; developerAddress: string;
  agreementReference: string; bankAccount: string;
}

const missing = (v: string, label: string) => v.trim() || `[UZUPEŁNIJ: ${label}]`;
const p = (text: string, opts: { bold?: boolean; align?: (typeof AlignmentType)[keyof typeof AlignmentType] } = {}) =>
  new Paragraph({ alignment: opts.align, spacing: { after: 160 }, children: [new TextRun({ text, bold: opts.bold, font: "Times New Roman", size: 24 })] });

const cell = (text: string, bold = false) =>
  new TableCell({ children: [new Paragraph({ children: [new TextRun({ text, bold, font: "Times New Roman", size: 22 })] })] });

function addDays(iso: string, n: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export async function buildLetter(parties: Parties, penalties: PenaltyResult[], capped: boolean, justification: string): Promise<Blob> {
  const total = penalties.reduce((a, x) => a + demanded(x, capped), 0n);
  const today = new Date().toISOString().slice(0, 10);
  const rows = penalties.filter((x) => x.uncappedGrosze !== null).map((x) => new TableRow({
    children: [
      cell(EVENT_LABELS[x.event].replace(/^./, (c) => c.toUpperCase())),
      cell(`${fmtDate(addDays(x.effectiveDeadline.deadline, 1))} – ${fmtDate(x.endDate)}${x.ongoing ? " (trwa)" : ""}`),
      cell(String(x.days)),
      cell(formatPln(demanded(x, capped))),
    ],
  }));
  const doc = new Document({
    sections: [{
      children: [
        p("PROJEKT — do weryfikacji i podpisu przez pełnomocnika", { bold: true, align: AlignmentType.CENTER }),
        p(missing(parties.firmName, "nazwa kancelarii")),
        p(`${missing(parties.firmCity, "miejscowość")}, dnia ${fmtDate(today)}`, { align: AlignmentType.RIGHT }),
        p(missing(parties.developerName, "nazwa dewelopera")),
        p(missing(parties.developerAddress, "adres dewelopera")),
        p("PRZEDSĄDOWE WEZWANIE DO ZAPŁATY", { bold: true, align: AlignmentType.CENTER }),
        p(`Działając w imieniu i na rzecz ${missing(parties.clientName, "mocodawca")} (${missing(parties.clientAddress, "adres mocodawcy")}), ` +
          `na podstawie udzielonego pełnomocnictwa, w związku z ${missing(parties.agreementReference, "data i numer umowy deweloperskiej")}, niniejszym:`),
        p(`wzywam do zapłaty kwoty ${formatPln(total)} tytułem kar umownych za opóźnienie, w terminie ${config.letter.payment_deadline_days} dni ` +
          `od dnia doręczenia niniejszego wezwania, na rachunek bankowy nr ${missing(parties.bankAccount, "numer rachunku")}.`),
        p("Wyliczenie kary umownej:"),
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          rows: [new TableRow({ children: ["Tytuł", "Okres opóźnienia", "Dni", "Kwota"].map((t) => cell(t, true)) }), ...rows],
        }),
        p(""),
        p("Uzasadnienie", { bold: true }),
        ...justification.split(/\n\s*\n/).map((para) => p(para.trim())),
        p(config.letter.legal_basis || "[UZUPEŁNIJ: podstawa prawna roszczenia]"),
        p("Brak zapłaty we wskazanym terminie spowoduje skierowanie sprawy na drogę postępowania sądowego bez dalszego wezwania."),
        p(missing(parties.lawyer, "pełnomocnik"), { align: AlignmentType.RIGHT }),
      ],
    }],
  });
  return Packer.toBlob(doc);
}
