// Zod mirror of pipeline/schema.py and pipeline/clauses.py (model output, without code-owned fields).
// The JSON schema sent to the model is schemas/extraction_model_output.json (generated from Pydantic),
// so the two definitions are checked against each other in shared.test.ts.
import { z } from "zod";

export const Confidence = z.enum(["high", "medium", "low"]);

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "expected YYYY-MM-DD");

export function field<T extends z.ZodTypeAny>(value: T) {
  return z
    .object({
      value: value.nullable(),
      quote: z.string().nullable(),
      page: z.number().int().min(1).nullable(),
      document_id: z.string().nullable(),
      confidence: Confidence,
    })
    .strict();
}

export const AnnexDeadline = z
  .object({
    date: isoDate,
    field: z.enum(["handover_deadline", "transfer_deadline"]),
    annex_no: z.number().int().nullable(),
  })
  .strict();

export const PenaltyCap = z.object({ type: z.enum(["percent", "amount"]), value: z.number() }).strict();
export const PenaltyBasis = z.enum(["percent_of_price_per_day", "fixed_per_day", "statutory_interest", "other"]);
export const PenaltyEvent = z.enum(["handover_delay", "transfer_delay"]);

export const Extraction = z
  .object({
    developer_name: field(z.string()),
    agreement_reference: field(z.string()),
    agreement_date: field(isoDate),
    price_gross: field(z.number()),
    handover_deadline: field(isoDate),
    transfer_deadline: field(isoDate),
    annex_deadlines: z.array(field(AnnexDeadline)),
    penalty_basis: field(PenaltyBasis),
    penalty_rate: field(z.number()),
    penalty_cap: field(PenaltyCap),
    penalty_events: field(z.array(PenaltyEvent)),
    liability_exclusions: z.array(field(z.string())),
    exclusive_penalty_clause: field(z.boolean()),
    waiver_of_claims: field(z.boolean()),
    actual_handover_date: field(isoDate),
    actual_transfer_date: field(isoDate),
  })
  .strict();

export const ClauseFlag = z
  .object({
    clause_id: z.string(),
    quote: z.string(),
    page: z.number().int().nullable(),
    document_id: z.string().nullable(),
    reasoning: z.string(),
    confidence: Confidence,
  })
  .strict();

export const ClauseFlags = z.object({ flags: z.array(ClauseFlag) }).strict();
export const Justification = z.object({ justification: z.string() }).strict();
export const DocumentType = z.enum(["development_agreement", "annex", "handover_protocol", "transfer_deed", "other"]);
export const Classification = z.object({
  documents: z.array(z.object({ document_id: z.string(), type: DocumentType, confidence: Confidence }).strict()),
}).strict();

export type Extraction = z.infer<typeof Extraction>;
export type ClauseFlag = z.infer<typeof ClauseFlag>;
export type FieldT = {
  value: unknown;
  quote: string | null;
  page: number | null;
  document_id: string | null;
  confidence: "high" | "medium" | "low";
};

/** All fields with their paths, like Extraction.iter_fields() in Python. */
export function iterFields(ex: Extraction): [string, FieldT][] {
  const out: [string, FieldT][] = [];
  for (const [name, item] of Object.entries(ex)) {
    if (Array.isArray(item)) item.forEach((f, i) => out.push([`${name}[${i}]`, f as FieldT]));
    else out.push([name, item as FieldT]);
  }
  return out;
}
