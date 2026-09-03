"""
Central configuration for api-pilot backend.

Settings are loaded from environment variables (and optionally a .env file).
All settings have sensible defaults so the app starts without a .env present.

Usage:
    from app.config import get_settings
    settings = get_settings()
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "api-pilot"
    app_env: str = "development"  # development | staging | production
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "postgresql+asyncpg://api_pilot:api_pilot_dev@localhost:5432/api_pilot"
    db_echo: bool = False       # SQL echo logging — set True in dev to see queries
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_pre_ping: bool = True

    # Storage
    storage_backend: str = "local"
    storage_local_dir: str = "storage"

    # LLM
    llm_provider: str = "nvidia_nim"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 120.0
    nvidia_api_key: str | None = None
    groq_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"

    # Probe-grounded generation — replay a cURL-imported endpoint's stored
    # example request once before generating tests, so body-level
    # validations are grounded in a real observed response instead of a
    # guess (app/services/probe_service.py). Off by default: this is the
    # rollback switch — set ENABLE_PROBE_GENERATION=false to disable
    # probing entirely without touching anything else.
    enable_probe_generation: bool = False


def get_settings() -> Settings:
    return Settings()
