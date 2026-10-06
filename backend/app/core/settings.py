"""Environment-driven settings: secrets and deployment wiring only.

Tunable numbers (weights, limits, model choices) live in ``config/*.yaml`` and
are loaded by :mod:`app.core.config`, never here.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: SecretStr = Field(
        description="SQLAlchemy async URL, e.g. postgresql+asyncpg://user:pass@host/db",
    )
    redis_url: str = "redis://localhost:6379/0"

    config_dir: Path = BACKEND_ROOT / "config"

    # File storage (ARCHITECTURE.md section 6): "local" disk, or "s3" for a
    # private S3-compatible bucket when deployed (Cloudflare R2, Backblaze B2).
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: Path = BACKEND_ROOT.parent / "data" / "storage"
    s3_bucket: str | None = None
    # R2: https://<account id>.r2.cloudflarestorage.com; empty for AWS itself.
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    # Downloaded embedding models (about 70 MB for the default).
    model_cache_dir: Path = BACKEND_ROOT.parent / "data" / "models"

    # Required from Phase 5; optional until the AI layer exists.
    anthropic_api_key: SecretStr | None = None

    # Web Push (Phase 11). Generate with `make vapid-keys`, which writes them
    # to .env. Push is off until all three are set.
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    # A contact the push services can reach, e.g. mailto:you@example.com.
    vapid_subject: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
