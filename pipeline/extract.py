"""Step 3 + 4: extraction with quotes, then quote verification by code."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.documents import Document, render_document
from pipeline.llm import LLMClient, call_structured
from pipeline.schema import Extraction, model_output_json_schema
from pipeline.settings import StepSettings, load_step, read_prompt
from pipeline.verify_quotes import QuoteIssue, verify_extraction


@dataclass
class ExtractionResult:
    extraction: Extraction
    issues: list[QuoteIssue]


def extract_case(
    client: LLMClient, case_id: str, docs: list[Document], settings: StepSettings | None = None
) -> ExtractionResult:
    settings = settings or load_step("extract")
    system = [{
        "type": "text",
        "text": read_prompt("extract_system.md"),
        "cache_control": {"type": "ephemeral"},
    }]
    content = [{"type": "text", "text": render_document(d)} for d in docs]
    content.append({"type": "text", "text": "Extract the case card from the documents above."})
    extraction = call_structured(
        client, "extract", case_id, settings, system, content, model_output_json_schema(), Extraction,
    )
    issues = verify_extraction(extraction, {d.id: d.pages for d in docs})
    return ExtractionResult(extraction, issues)
