"""Test doubles: a scripted LLM client and a tiny PDF writer (no real documents)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.llm import LLMResponse
from pipeline.settings import StepSettings

SETTINGS = StepSettings(model="test-model", max_tokens=1000, effort="low")


class FakeLLM:
    """Returns scripted responses in order and records requests."""

    def __init__(self, *responses: LLMResponse | dict | str) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, settings, system, messages, schema):
        self.calls.append({"settings": settings, "system": system, "messages": messages, "schema": schema})
        item = self.responses.pop(0)
        if isinstance(item, LLMResponse):
            return item
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return LLMResponse(text=text, stop_reason="end_turn", input_tokens=10, output_tokens=5)


def write_pdf(path: Path, pages: list[str]) -> Path:
    """Minimal valid PDF with one line of ASCII text per page (Helvetica)."""
    objects: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 50 780 Td ({safe}) Tj ET".encode() if text else b""
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path
