from decimal import Decimal

import pytest
import yaml
from pydantic import BaseModel

from pipeline.llm import CallRecord, LLMError, LLMResponse, call_structured
from pipeline.settings import CONFIG_DIR
from pipeline.tests.fakes import SETTINGS, FakeLLM
from pipeline.usage import format_usd, load_pricing


class Out(BaseModel):
    ok: bool


class Recording(FakeLLM):
    def __init__(self, *responses):
        super().__init__(*responses)
        self.records: list[CallRecord] = []

    def record_call(self, record):
        self.records.append(record)


def test_pricing_cost_in_microdollars(tmp_path):
    path = tmp_path / "pricing.yaml"
    path.write_text(
        "source: test\nverified: false\nas_of: 2026-01-01\nmodels:\n"
        '  m: {input: "4.00", output: "20.00", cache_write: "5.00", cache_read: "0.20"}\n',
        encoding="utf-8")
    pricing = load_pricing(path)
    # 10 000 in x $4 + 2 000 out x $20 + 1 000 write x $5 + 50 000 read x $0.20 (per 1M tokens)
    # = 0.04 + 0.04 + 0.005 + 0.01 = $0.095
    assert pricing.cost_microusd("m", 10_000, 2_000, 1_000, 50_000) == 95_000
    assert pricing.cost_microusd("unknown", 1, 1) is None
    assert pricing.models["m"].input == Decimal("4.00") and not pricing.verified
    assert format_usd(95_000) == "$0.0950" and format_usd(None) == "—"


def test_pricing_smallest_unit_and_missing_file(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text('models:\n  m: {input: "1", output: "1", cache_write: "1", cache_read: "1"}\n', encoding="utf-8")
    assert load_pricing(path).cost_microusd("m", 1, 0) == 1  # 1 token x $1 / 1M = 1 micro-dollar
    assert load_pricing(tmp_path / "none.yaml").models == {}


def test_shipped_pricing_covers_configured_models():
    pricing = load_pricing()
    steps = yaml.safe_load((CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))["steps"]
    assert {s["model"] for s in steps.values()} <= set(pricing.models)
    assert pricing.source and pricing.verified is False


def test_call_structured_records_every_attempt():
    llm = Recording(
        "not json",
        LLMResponse(text='{"ok": true}', stop_reason="end_turn", input_tokens=100, output_tokens=7,
                    cache_creation_input_tokens=30, cache_read_input_tokens=40, model="served"),
    )
    out = call_structured(llm, "extract", "case1", SETTINGS, [], [{"type": "text", "text": "x"}], {}, Out)
    assert out.ok
    first, second = llm.records
    assert (first.attempt, first.outcome, first.input_tokens) == (1, "invalid_output", 10)
    assert (second.attempt, second.outcome, second.served_model) == (2, "ok", "served")
    assert (second.cache_creation_input_tokens, second.cache_read_input_tokens) == (30, 40)
    assert second.case_id == "case1" and second.step == "extract" and second.model == "test-model"


def test_failed_recording_does_not_break_the_call():
    class Broken(FakeLLM):
        def record_call(self, record):
            raise RuntimeError("db down")

    out = call_structured(Broken('{"ok": true}'), "classify", "c", SETTINGS, [], [], {}, Out)
    assert out.ok


def test_refusal_and_truncation_are_recorded():
    llm = Recording(LLMResponse(text="", stop_reason="refusal"))
    with pytest.raises(LLMError):
        call_structured(llm, "clauses", "c", SETTINGS, [], [], {}, Out)
    assert [r.outcome for r in llm.records] == ["refusal"]

    llm = Recording(LLMResponse(text="", stop_reason="max_tokens"), LLMResponse(text="", stop_reason="max_tokens"))
    with pytest.raises(LLMError):
        call_structured(llm, "extract", "c", SETTINGS, [], [], {}, Out)
    assert [r.outcome for r in llm.records] == ["truncated", "truncated"]
