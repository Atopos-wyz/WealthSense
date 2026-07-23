"""Strongly typed configuration shared by public infrastructure and Agents."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEVELOPMENT_JWT_SECRET = "development-only-change-me"


def _wealthsense_alias(name: str) -> AliasChoices:
    return AliasChoices(f"WEALTHSENSE_{name}", name)


class Settings(BaseSettings):
    """Central configuration for shared services and the operator Agent."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    app_name: str = "WealthSense"
    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "WEALTHSENSE_APP_ENV"),
    )
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    jwt_secret_key: SecretStr = SecretStr(DEFAULT_DEVELOPMENT_JWT_SECRET)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)
    jwt_issuer: str = Field(
        default="wealthsense",
        validation_alias=AliasChoices("JWT_ISSUER", "WEALTHSENSE_JWT_ISSUER"),
    )
    jwt_audience: str = "wealthsense-api"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = "finance"
    mysql_user: str = "finance_app"
    mysql_password: SecretStr = SecretStr("not-configured")
    mysql_pool_size: int = Field(default=5, ge=1, le=100)
    mysql_max_overflow: int = Field(default=10, ge=0, le=200)
    mysql_pool_recycle_seconds: int = Field(default=1800, ge=60)

    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)
    redis_password: SecretStr = SecretStr("not-configured")
    redis_max_connections: int = Field(default=20, ge=1, le=1000)

    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("not-configured")
    neo4j_database: str = "neo4j"
    neo4j_max_connection_pool_size: int = Field(default=20, ge=1, le=1000)

    milvus_host: str = "127.0.0.1"
    milvus_port: int = Field(default=19530, ge=1, le=65535)
    milvus_user: str = "root"
    milvus_root_password: SecretStr = SecretStr("not-configured")
    milvus_database: str = "default"
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    mysql_url: SecretStr | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("MYSQL_URL"),
    )
    redis_url: SecretStr | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("REDIS_URL"),
    )
    ssh_tunnel_enabled: bool = Field(
        default=False,
        validation_alias=_wealthsense_alias("SSH_TUNNEL_ENABLED"),
    )
    ssh_host: str | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("SSH_HOST"),
    )
    ssh_port: int = Field(
        default=22,
        ge=1,
        le=65535,
        validation_alias=_wealthsense_alias("SSH_PORT"),
    )
    ssh_username: str | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("SSH_USERNAME"),
    )
    ssh_password: SecretStr | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("SSH_PASSWORD"),
    )
    ssh_known_hosts: str = Field(
        default="~/.ssh/known_hosts",
        validation_alias=_wealthsense_alias("SSH_KNOWN_HOSTS"),
    )
    ssh_remote_mysql_host: str = Field(
        default="127.0.0.1",
        validation_alias=_wealthsense_alias("SSH_REMOTE_MYSQL_HOST"),
    )
    ssh_remote_mysql_port: int = Field(
        default=3306,
        ge=1,
        le=65535,
        validation_alias=_wealthsense_alias("SSH_REMOTE_MYSQL_PORT"),
    )
    ssh_remote_redis_host: str = Field(
        default="127.0.0.1",
        validation_alias=_wealthsense_alias("SSH_REMOTE_REDIS_HOST"),
    )
    ssh_remote_redis_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        validation_alias=_wealthsense_alias("SSH_REMOTE_REDIS_PORT"),
    )
    ssh_keepalive_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        validation_alias=_wealthsense_alias("SSH_KEEPALIVE_SECONDS"),
    )
    confirmation_ttl_seconds: int = Field(
        default=900,
        ge=60,
        validation_alias=_wealthsense_alias("CONFIRMATION_TTL_SECONDS"),
    )
    risk_review_ttl_seconds: int = Field(
        default=300,
        ge=30,
        validation_alias=_wealthsense_alias("RISK_REVIEW_TTL_SECONDS"),
    )
    idempotency_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        validation_alias=_wealthsense_alias("IDEMPOTENCY_TTL_SECONDS"),
    )
    jwt_secret: str = Field(
        default="development-jwt-secret-change-me",
        validation_alias=_wealthsense_alias("JWT_SECRET"),
    )
    customer_event_hmac_secret: str = Field(
        default="dev-customer-event-secret",
        validation_alias=_wealthsense_alias("CUSTOMER_EVENT_HMAC_SECRET"),
    )
    advisor_event_hmac_secret: str = Field(
        default="dev-advisor-event-secret",
        validation_alias=_wealthsense_alias("ADVISOR_EVENT_HMAC_SECRET"),
    )
    risk_event_hmac_secret: str = Field(
        default="dev-risk-event-secret",
        validation_alias=_wealthsense_alias("RISK_EVENT_HMAC_SECRET"),
    )
    analyst_event_hmac_secret: str = Field(
        default="dev-analyst-event-secret",
        validation_alias=_wealthsense_alias("ANALYST_EVENT_HMAC_SECRET"),
    )
    operator_event_hmac_secret: str = Field(
        default="dev-operator-event-secret",
        validation_alias=_wealthsense_alias("OPERATOR_EVENT_HMAC_SECRET"),
    )
    event_stream_key: str = Field(
        default="agent:events:durable",
        validation_alias=_wealthsense_alias("EVENT_STREAM_KEY"),
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("LLM_BASE_URL"),
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("LLM_API_KEY"),
    )
    llm_model: str | None = Field(
        default=None,
        validation_alias=_wealthsense_alias("LLM_MODEL"),
    )
    llm_timeout_seconds: float = Field(
        default=10,
        gt=0,
        le=60,
        validation_alias=_wealthsense_alias("LLM_TIMEOUT_SECONDS"),
    )
    llm_confidence_threshold: float = Field(
        default=0.75,
        ge=0,
        le=1,
        validation_alias=_wealthsense_alias("LLM_CONFIDENCE_THRESHOLD"),
    )
    trusted_agent_ids: set[str] = Field(
        default={
            "customer",
            "advisor",
            "risk",
            "analyst",
            "operator",
        },
        validation_alias=_wealthsense_alias("TRUSTED_AGENT_IDS"),
    )

    @field_validator(
        "mysql_password",
        "redis_password",
        "neo4j_password",
        "milvus_root_password",
    )
    @classmethod
    def validate_non_empty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("数据库密码不能为空")
        return value

    @field_validator(
        "mysql_database",
        "mysql_user",
        "neo4j_user",
        "neo4j_database",
        "milvus_database",
    )
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("配置值不能为空")
        return value

    @field_validator("neo4j_uri")
    @classmethod
    def validate_neo4j_uri(cls, value: str) -> str:
        if not value.startswith(("bolt://", "bolt+s://", "neo4j://", "neo4j+s://")):
            raise ValueError("NEO4J_URI 必须使用 Neo4j 或 Bolt URI 协议")
        return value

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("LLM_BASE_URL must be a valid HTTP(S) URL")
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and parsed.hostname not in loopback_hosts:
            raise ValueError(
                "remote LLM_BASE_URL must use HTTPS; "
                "HTTP is allowed only for loopback hosts"
            )
        return value

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if (
            self.app_env == "production"
            and self.jwt_secret_key.get_secret_value()
            == DEFAULT_DEVELOPMENT_JWT_SECRET
        ):
            raise ValueError("生产环境必须配置 JWT_SECRET_KEY")
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
    def milvus_uri(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"

    @property
    def has_external_infrastructure(self) -> bool:
        return bool(self.mysql_url and self.redis_url)

    @property
    def has_llm_intent_recognition(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def event_hmac_secrets(self) -> dict[str, str]:
        return {
            "customer": self.customer_event_hmac_secret,
            "advisor": self.advisor_event_hmac_secret,
            "risk": self.risk_event_hmac_secret,
            "analyst": self.analyst_event_hmac_secret,
            "operator": self.operator_event_hmac_secret,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
