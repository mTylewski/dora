"""Thin wrapper over the Claude API for fixed pipeline steps.

The model gets no tools and no network access (CLAUDE.md, section 3, rule 4).
Output is constrained with structured outputs (output_config.format) and then
validated with Pydantic; one retry on invalid output, then an error.
Logs contain only technical metadata, never document content.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from pipeline.settings import StepSettings

log = logging.getLogger("claims.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"

M = TypeVar("M", bound=BaseModel)


class LLMError(RuntimeError):
    """Step failed; `code` is safe to show in the UI and logs."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass
class LLMResponse:
    text: str
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    content: list[Any] = field(default_factory=list)  # raw blocks, echoed back on retry


class LLMClient(Protocol):
    def complete(
        self,
        settings: StepSettings,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> LLMResponse: ...


class AnthropicClient:
    """Production client. Uses streaming so long outputs don't hit HTTP timeouts."""

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def complete(self, settings, system, messages, schema):  # pragma: no cover - network
        params: dict[str, Any] = {
            "model": settings.model,
            "max_tokens": settings.max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        if settings.effort:
            params["output_config"]["effort"] = settings.effort
        if settings.refusal_fallback:
            stream_cm = self._client.beta.messages.stream(
                betas=[FALLBACK_BETA], fallbacks="default", **params
            )
        else:
            stream_cm = self._client.messages.stream(**params)
        with stream_cm as stream:
            message = stream.get_final_message()
        text = next((b.text for b in message.content if b.type == "text"), "")
        return LLMResponse(
            text=text,
            stop_reason=message.stop_reason,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            content=list(message.content),
        )


def call_structured(
    client: LLMClient,
    step: str,
    case_id: str,
    settings: StepSettings,
    system: list[dict[str, Any]],
    user_content: list[dict[str, Any]],
    schema: dict[str, Any],
    output_model: type[M],
) -> M:
    """Run one step and return validated output. One retry, then LLMError."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
    last_error = ""
    for attempt in (1, 2):
        started = time.monotonic()
        try:
            response = client.complete(settings, system, messages, schema)
        except anthropic.APIStatusError as exc:  # pragma: no cover - network
            log.warning("case=%s step=%s attempt=%d api_status=%s", case_id, step, attempt, exc.status_code)
            raise LLMError("api_error", str(exc.status_code)) from exc
        except anthropic.APIConnectionError as exc:  # pragma: no cover - network
            log.warning("case=%s step=%s attempt=%d api_connection_error", case_id, step, attempt)
            raise LLMError("api_connection_error") from exc
        log.info(
            "case=%s step=%s attempt=%d model=%s ms=%d in_tokens=%d out_tokens=%d stop=%s",
            case_id, step, attempt, settings.model, int((time.monotonic() - started) * 1000),
            response.input_tokens, response.output_tokens, response.stop_reason,
        )
        if response.stop_reason == "refusal":
            raise LLMError("refusal")
        if response.stop_reason == "max_tokens":
            last_error = "output truncated (max_tokens)"
        else:
            try:
                data = json.loads(response.text, parse_float=Decimal)
                return output_model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = _short_error(exc)
        log.warning("case=%s step=%s attempt=%d invalid_output", case_id, step, attempt)
        messages = messages + [
            {"role": "assistant", "content": response.content or [{"type": "text", "text": response.text}]},
            {"role": "user", "content": [{"type": "text", "text":
                f"The previous answer was rejected by validation: {last_error}. "
                "Return the complete corrected JSON only."}]},
        ]
    raise LLMError("invalid_output", last_error)


def _short_error(exc: Exception) -> str:
    """Validation error summary without echoing document content (input values)."""
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]]
        return "; ".join(parts)
    return type(exc).__name__
