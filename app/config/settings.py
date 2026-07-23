"""从环境变量加载的强类型应用配置。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEVELOPMENT_JWT_SECRET = "development-only-change-me"


class Settings(BaseSettings):
    """公共应用基础设施的集中配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "WealthSense"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    jwt_secret_key: SecretStr = SecretStr(DEFAULT_DEVELOPMENT_JWT_SECRET)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)
    jwt_issuer: str = "wealthsense"
    jwt_audience: str = "wealthsense-api"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = "finance"
    mysql_user: str = "finance_app"
    mysql_password: SecretStr
    mysql_pool_size: int = Field(default=5, ge=1, le=100)
    mysql_max_overflow: int = Field(default=10, ge=0, le=200)
    mysql_pool_recycle_seconds: int = Field(default=1800, ge=60)

    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)
    redis_password: SecretStr
    redis_max_connections: int = Field(default=20, ge=1, le=1000)

    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr
    neo4j_database: str = "neo4j"
    neo4j_max_connection_pool_size: int = Field(default=20, ge=1, le=1000)

    milvus_host: str = "127.0.0.1"
    milvus_port: int = Field(default=19530, ge=1, le=65535)
    milvus_user: str = "root"
    milvus_root_password: SecretStr
    milvus_database: str = "default"

    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    embedding_provider: Literal["bge", "hashing"] = "bge"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_dimension: int = Field(default=1024, ge=1)
    embedding_batch_size: int = Field(default=16, ge=1, le=128)

    knowledge_chunk_size: int = Field(default=512, ge=64, le=8192)
    knowledge_chunk_overlap: int = Field(default=64, ge=0, le=1024)
    knowledge_search_min_score: float = Field(default=0.7, ge=0, le=1)

    session_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    session_max_messages: int = Field(default=20, ge=2, le=200)
    session_token_budget: int = Field(default=4096, ge=256, le=32768)
    nl2sql_cache_ttl_seconds: int = Field(default=600, ge=1, le=86400)
    nl2sql_max_rows: int = Field(default=100, ge=1, le=1000)

    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "qwen3.7-plus"
    llm_enable_thinking: bool = False
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)

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
        "embedding_model",
        "llm_model",
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

    @model_validator(mode="after")
    def validate_production_security(self) -> Settings:
        if (
            self.app_env == "production"
            and self.jwt_secret_key.get_secret_value() == DEFAULT_DEVELOPMENT_JWT_SECRET
        ):
            raise ValueError("生产环境必须配置 JWT_SECRET_KEY")
        if self.knowledge_chunk_overlap >= self.knowledge_chunk_size:
            raise ValueError("KNOWLEDGE_CHUNK_OVERLAP 必须小于 KNOWLEDGE_CHUNK_SIZE")
        return self

    @property
    def milvus_uri(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回按约定只读的缓存配置实例。"""

    return Settings()


def clear_settings_cache() -> None:
    """清除配置缓存，主要用于测试和受控重载。"""

    get_settings.cache_clear()
