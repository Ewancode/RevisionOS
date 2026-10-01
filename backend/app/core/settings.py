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

    # Required from Phase 5; optional until the AI layer exists.
    anthropic_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
