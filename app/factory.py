"""Build production Services from environment variables."""

from __future__ import annotations

from app.config import Settings
from app.db import make_sessionmaker
from app.services import Services, ThreadQueue


def build_services(settings: Settings | None = None) -> Services:  # pragma: no cover - env wiring
    from app.jobs import RQQueue
    from pipeline.llm import AnthropicClient
    from pipeline.ner import configured_detectors
    from pipeline.ocr import ocr_page, tesseract_available

    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return Services(
        settings=settings,
        sessions=make_sessionmaker(settings.database_url),
        llm_factory=AnthropicClient,
        queue=RQQueue(settings.redis_url) if settings.redis_url else ThreadQueue(),
        ocr=ocr_page if tesseract_available() else None,
        detectors=configured_detectors(),
    )
