"""Build production Services from environment variables."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.config import Settings
from app.db import make_sessionmaker
from app.services import Services, ThreadQueue


def configure_logging(log_dir: Path) -> None:
    """Technical log (ids, steps, times, tokens, error codes; never document content) to the
    console and to a rotating file: 5 files x 5 MB in `log_dir`."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("claims")
    if any(getattr(h, "_claims", False) for h in logger.handlers):
        return  # already configured (e.g. app factory called twice)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(log_dir / "claims.log", maxBytes=5_000_000,
                                                        backupCount=5, encoding="utf-8")
    console = logging.StreamHandler()
    for handler in (file_handler, console):
        handler.setFormatter(fmt)
        handler._claims = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


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
