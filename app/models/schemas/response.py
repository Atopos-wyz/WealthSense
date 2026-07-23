"""公共 API 响应数据模型。"""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PublicSchema(BaseModel):
    """公共请求与响应模型共用的基础模型。"""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class ErrorItem(PublicSchema):
    """单条参数校验或领域错误详情。"""

    location: list[str | int] = Field(default_factory=list)
    message: str
    error_type: str | None = None


class ApiResponse(PublicSchema, Generic[T]):
    """项目接口约定使用的统一响应结构。"""

    code: int
    message: str
    data: T | None = None
    trace_id: str = Field(default_factory=lambda: str(uuid4()))


class PageData(PublicSchema, Generic[T]):
    """通用分页集合数据。"""

    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        *,
        page: int,
        page_size: int,
        total: int,
    ) -> PageData[T]:
        return cls(
            items=list(items),
            page=page,
            page_size=page_size,
            total=total,
            pages=ceil(total / page_size) if total else 0,
        )
