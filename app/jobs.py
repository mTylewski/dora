"""Background jobs. With CLAIMS_REDIS_URL they run in an RQ worker
(`rq worker claims --url $CLAIMS_REDIS_URL`), otherwise inline."""

from __future__ import annotations

from functools import lru_cache

from app.services import Services


class RQQueue:  # pragma: no cover - needs Redis
    def __init__(self, redis_url: str) -> None:
        from redis import Redis
        from rq import Queue

        self._queue = Queue("claims", connection=Redis.from_url(redis_url), default_timeout=1800)

    def enqueue(self, job: str, case_id: str) -> None:
        self._queue.enqueue(f"app.jobs.{job}", case_id, job_timeout=1800, failure_ttl=86400)


_override: Services | None = None


def use_services(services: Services | None) -> None:
    """Let the web app (or tests) share one Services instance with inline jobs."""
    global _override
    _override = services


@lru_cache(maxsize=1)
def _worker_services() -> Services:  # pragma: no cover - worker process
    from app.factory import build_services

    return build_services()


def services() -> Services:
    return _override or _worker_services()


def prepare_job(case_id: str) -> None:
    services().run_prepare(case_id)


def analyze_job(case_id: str) -> None:
    services().run_analyze(case_id)
