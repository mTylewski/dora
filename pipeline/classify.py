"""Step 2: document classification (small model, opening pages only)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from pipeline.documents import Document, render_document
from pipeline.llm import LLMClient, call_structured
from pipeline.schema import Confidence, DocumentType, strict_schema
from pipeline.settings import StepSettings, load_step, read_prompt

CLASSIFY_PAGES = 3


class DocumentClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    type: DocumentType
    confidence: Confidence


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[DocumentClass]


def classify_documents(
    client: LLMClient, case_id: str, docs: list[Document], settings: StepSettings | None = None
) -> list[DocumentClass]:
    """Set doc.type on every document; unknown or missing results become `other`."""
    settings = settings or load_step("classify")
    system = [{"type": "text", "text": read_prompt("classify_system.md")}]
    text = "\n\n".join(render_document(d, CLASSIFY_PAGES) for d in docs)
    result = call_structured(
        client, "classify", case_id, settings, system,
        [{"type": "text", "text": text}],
        strict_schema(Classification.model_json_schema()), Classification,
    )
    by_id = {c.document_id: c for c in result.documents}
    out: list[DocumentClass] = []
    for doc in docs:
        item = by_id.get(doc.id) or DocumentClass(document_id=doc.id, type=DocumentType.OTHER,
                                                  confidence=Confidence.LOW)
        doc.type = item.type
        out.append(item)
    return out
