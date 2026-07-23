from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WEALTHSENSE_",
        extra="ignore",
    )

    app_name: str = "WealthSense Business Operator"
    app_env: str = "development"
    mysql_url: str | None = None
    redis_url: str | None = None
    confirmation_ttl_seconds: int = Field(default=900, ge=60)
    risk_review_ttl_seconds: int = Field(default=300, ge=30)
    idempotency_ttl_seconds: int = Field(default=3600, ge=60)
    trusted_agent_ids: set[str] = {
        "customer",
        "advisor",
        "risk",
        "analyst",
        "operator",
    }

    @property
    def has_external_infrastructure(self) -> bool:
        return bool(self.mysql_url and self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()

