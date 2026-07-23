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
    jwt_secret: str = "development-jwt-secret-change-me"
    jwt_issuer: str = "wealthsense"
    customer_event_hmac_secret: str = "dev-customer-event-secret"
    advisor_event_hmac_secret: str = "dev-advisor-event-secret"
    risk_event_hmac_secret: str = "dev-risk-event-secret"
    analyst_event_hmac_secret: str = "dev-analyst-event-secret"
    operator_event_hmac_secret: str = "dev-operator-event-secret"
    event_stream_key: str = "agent:events:durable"
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

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def event_hmac_secrets(self) -> dict[str, str]:
        return {
            "customer": self.customer_event_hmac_secret,
            "advisor": self.advisor_event_hmac_secret,
            "risk": self.risk_event_hmac_secret,
            "analyst": self.analyst_event_hmac_secret,
            "operator": self.operator_event_hmac_secret,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
