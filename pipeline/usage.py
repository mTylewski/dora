"""Cost estimate of API calls from config/pricing.yaml (deterministic code, Decimal).

Costs are kept as integer micro-dollars (1 USD = 1 000 000) so sums are exact.
The Anthropic bill is authoritative; this is an estimate for evaluation and monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import yaml

from pipeline.settings import CONFIG_DIR

MICRO = Decimal(1_000_000)
PER_TOKENS = Decimal(1_000_000)  # prices are per 1M tokens


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


@dataclass(frozen=True)
class Pricing:
    models: dict[str, ModelPrice]
    source: str
    verified: bool
    as_of: str

    def cost_microusd(self, model: str | None, input_tokens: int, output_tokens: int,
                      cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0) -> int | None:
        """Estimated cost in micro-dollars, or None for a model without a price."""
        price = self.models.get(model or "")
        if price is None:
            return None
        usd = (
            Decimal(input_tokens) * price.input
            + Decimal(output_tokens) * price.output
            + Decimal(cache_creation_input_tokens) * price.cache_write
            + Decimal(cache_read_input_tokens) * price.cache_read
        ) / PER_TOKENS
        return int((usd * MICRO).to_integral_value(rounding=ROUND_HALF_UP))


def load_pricing(path: Path | None = None) -> Pricing:
    path = path or CONFIG_DIR / "pricing.yaml"
    if not path.exists():
        return Pricing({}, "", False, "")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    models = {
        name: ModelPrice(*(Decimal(str(p[k])) for k in ("input", "output", "cache_write", "cache_read")))
        for name, p in (raw.get("models") or {}).items()
    }
    return Pricing(models, str(raw.get("source", "")), bool(raw.get("verified", False)), str(raw.get("as_of", "")))


@lru_cache(maxsize=1)
def default_pricing() -> Pricing:
    return load_pricing()


def format_usd(microusd: int | None) -> str:
    if microusd is None:
        return "—"
    usd = (Decimal(microusd) / MICRO).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return f"${usd}"
