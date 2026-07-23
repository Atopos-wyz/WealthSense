"""环境配置读取。"""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import make_url


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_url: str
    redis_url: str | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(".env 中缺少 DATABASE_URL")
    parsed_url = make_url(database_url)
    if (
        os.getenv("SSH_HOST")
        and parsed_url.host in {"127.0.0.1", "localhost"}
    ):
        tunnel_port = int(os.getenv("MYSQL_TUNNEL_PORT", "13306"))
        database_url = parsed_url.set(port=tunnel_port).render_as_string(
            hide_password=False
        )
    return Settings(
        app_name=os.getenv("APP_NAME", "WealthSense"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        database_url=database_url,
        redis_url=os.getenv("REDIS_URL"),
    )
