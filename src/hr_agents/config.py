"""Application configuration.

All settings are loaded from environment variables with the ``HRAGENTS_`` prefix,
falling back to a local ``.env`` file when present.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hr_agents.rbac import RoleId

Environment = Literal["local", "test", "staging", "production"]
StoreBackend = Literal["memory", "postgres"]


class ApiPrincipalSettings(BaseModel):
    """A role-bound API key (operator-managed principals)."""

    key: SecretStr
    role: RoleId = RoleId.HR_ADMIN
    actor_id: str = Field(default="api-key", min_length=1, max_length=200)


class Settings(BaseSettings):
    """Runtime configuration for the HRAgents platform."""

    model_config = SettingsConfigDict(
        env_prefix="HRAGENTS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "HRAgents"
    environment: Environment = "local"
    log_level: str = "INFO"
    debug: bool = False

    # Inbound API keys. Empty list = authentication disabled (local dev only).
    # Plain keys are treated as hr_admin; use api_principals for role-bound keys.
    api_keys: list[str] = Field(default_factory=list)
    api_principals: list[ApiPrincipalSettings] = Field(default_factory=list)

    # --- Persistence ---
    # Store backend: "memory" (tests, zero-config dev) or "postgres" (durable).
    store_backend: StoreBackend = "memory"
    database_url: str = "postgresql+asyncpg://hragents:hragents@localhost:5432/hragents"
    redis_url: str = "redis://localhost:6379/0"

    @property
    def sync_database_url(self) -> str:
        """Sync-driver URL for store adapters (psycopg); see ADR 0005."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    # --- Object storage ---
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key: str = "hragents"
    s3_secret_key: str = "hragents123"
    s3_bucket: str = "hragents-documents"

    # --- LLM ---
    # PydanticAI model string. The special value "test" runs agents fully offline.
    llm_model: str = "test"

    # --- External integrations ---
    github_token: str | None = None
    crossref_mailto: str = "team@example.com"

    # --- Messaging bridges ---
    messaging_sandbox: bool = True
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None
    telegram_bot_token: str | None = None
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "hragents@example.com"

    # --- Policy thresholds (defaults are the locked contract) ---
    auto_schedule_min_score: float = Field(default=0.85, ge=0.0, le=1.0)
    auto_schedule_max_variance: float = Field(default=0.05, ge=0.0, le=1.0)
    soft_rejection_floor: float = Field(default=0.70, ge=0.0, le=1.0)
    min_interviewer_slots: int = Field(default=2, ge=0)

    # --- Queue priority weights (P = a*S + b*e^(-l*dt) + g*A - d*R) ---
    priority_alpha: float = Field(default=0.55, ge=0.0, le=1.0)
    priority_beta: float = Field(default=0.25, ge=0.0, le=1.0)
    priority_gamma: float = Field(default=0.10, ge=0.0, le=1.0)
    priority_delta: float = Field(default=0.10, ge=0.0, le=1.0)
    priority_lambda_per_hour: float = Field(default=0.05, gt=0.0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
