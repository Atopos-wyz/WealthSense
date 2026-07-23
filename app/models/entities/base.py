"""ORM 基类（仅风控等自建实体使用，不改他人表）。"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
