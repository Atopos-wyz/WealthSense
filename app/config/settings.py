from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
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
    mysql_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    ssh_tunnel_enabled: bool = False
    ssh_host: str | None = None
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str | None = None
    ssh_password: SecretStr | None = None
    ssh_known_hosts: str = "~/.ssh/known_hosts"
    ssh_remote_mysql_host: str = "127.0.0.1"
    ssh_remote_mysql_port: int = Field(default=3306, ge=1, le=65535)
    ssh_remote_redis_host: str = "127.0.0.1"
    ssh_remote_redis_port: int = Field(default=6379, ge=1, le=65535)
    ssh_keepalive_seconds: int = Field(default=30, ge=5, le=300)
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

    @model_validator(mode="after")
    def validate_ssh_configuration(self) -> "Settings":
        if not self.ssh_tunnel_enabled:
            return self
        missing = [
            name
            for name, value in (
                ("mysql_url", self.mysql_url),
                ("redis_url", self.redis_url),
                ("ssh_host", self.ssh_host),
                ("ssh_username", self.ssh_username),
                ("ssh_password", self.ssh_password),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "SSH tunnel requires configuration: " + ", ".join(missing)
            )
        return self

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
