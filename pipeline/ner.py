"""Optional spaCy NER detector for names and places.

Model name comes from env CLAIMS_SPACY_MODEL (e.g. pl_core_news_lg).
Check the model's license for commercial use before enabling it (CLAUDE.md, section 13).
"""

from __future__ import annotations

import os
from collections.abc import Iterable

LABELS = {"persName": "OSOBA", "PER": "OSOBA", "placeName": "MIEJSCE", "geogName": "MIEJSCE"}


class SpacyDetector:  # pragma: no cover - requires a downloaded model
    def __init__(self, model: str) -> None:
        import spacy

        self._nlp = spacy.load(model, disable=["parser", "lemmatizer"])

    def detect(self, text: str) -> Iterable[tuple[str, str]]:
        for ent in self._nlp(text).ents:
            label = LABELS.get(ent.label_)
            if label:
                yield label, ent.text


def configured_detectors() -> list:
    model = os.environ.get("CLAIMS_SPACY_MODEL")
    return [SpacyDetector(model)] if model else []  # pragma: no cover - env dependent
