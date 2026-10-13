"""Application settings from environment variables (see deploy/.env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str | None
    secret_key: str
    mapping_key: str  # Fernet key for anonymization mappings and analysis data
    data_dir: Path
    retention_days: int
    require_anon_approval: bool
    secure_cookies: bool
    max_upload_mb: int

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.environ.get("CLAIMS_SECRET_KEY", "")
        mapping_key = os.environ.get("CLAIMS_MAPPING_KEY", "")
        if not secret or not mapping_key:
            raise RuntimeError("CLAIMS_SECRET_KEY and CLAIMS_MAPPING_KEY must be set")
        return cls(
            database_url=os.environ.get("CLAIMS_DATABASE_URL", "sqlite:///./data/claims.db"),
            redis_url=os.environ.get("CLAIMS_REDIS_URL") or None,
            secret_key=secret,
            mapping_key=mapping_key,
            data_dir=Path(os.environ.get("CLAIMS_DATA_DIR", "./data")),
            retention_days=int(os.environ.get("CLAIMS_RETENTION_DAYS", "180")),
            require_anon_approval=_bool("CLAIMS_REQUIRE_ANON_APPROVAL", True),
            secure_cookies=_bool("CLAIMS_SECURE_COOKIES", True),
            max_upload_mb=int(os.environ.get("CLAIMS_MAX_UPLOAD_MB", "50")),
        )
