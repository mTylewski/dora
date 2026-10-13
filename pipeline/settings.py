"""Paths and per-step model settings (config/models.yaml + env overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("CLAIMS_CONFIG_DIR", ROOT / "config"))
PROMPTS_DIR = ROOT / "prompts"
CLAUSES_DIR = ROOT / "clauses"
TEMPLATES_DIR = ROOT / "templates"


@dataclass(frozen=True)
class StepSettings:
    model: str
    max_tokens: int
    effort: str | None = None
    refusal_fallback: bool = False


def load_step(step: str, path: Path | None = None) -> StepSettings:
    path = path or CONFIG_DIR / "models.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)["steps"][step]
    return StepSettings(
        model=os.environ.get(f"CLAIMS_MODEL_{step.upper()}", raw["model"]),
        max_tokens=int(raw["max_tokens"]),
        effort=raw.get("effort"),
        refusal_fallback=bool(raw.get("refusal_fallback", False)),
    )


def read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")
