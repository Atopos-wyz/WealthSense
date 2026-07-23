"""知识库上传、查询、更新、删除和检索接口。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.dependencies import get_knowledge_service
from app.models.schemas import ApiResponse, PageData, Permission
from app.models.schemas.knowledge import (
    KnowledgeMetaResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeUpdateRequest,
    KnowledgeUploadResponse,
)
from app.service.knowledge import KnowledgeService
from app.utils.permissions import require_permissions
from app.view.response import success_response

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

ReadAccess = Annotated[
    object,
    Depends(require_permissions(Permission.KNOWLEDGE_READ)),
]
ManageAccess = Annotated[
    object,
    Depends(require_permissions(Permission.KNOWLEDGE_MANAGE)),
]


@router.post("/upload", response_model=ApiResponse[KnowledgeUploadResponse])
async def upload_knowledge(
    _: ManageAccess,
    file: Annotated[UploadFile, File()],
    knowledge_type: Annotated[
        Literal["FAQ", "产品说明", "政策法规", "操作指南", "市场研报"],
        Form(),
    ],
    title: Annotated[str | None, Form()] = None,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> ApiResponse[KnowledgeUploadResponse]:
    data = await file.read()
    item, chunk_count = await service.ingest(
        filename=file.filename or "uploaded-document",
        data=data,
        knowledge_type=knowledge_type,
        title=title,
        source_path=f"uploads/{file.filename or 'uploaded-document'}",
    )
    return success_response(
        KnowledgeUploadResponse(
            document=KnowledgeMetaResponse.model_validate(item),
            chunk_count=chunk_count,
        )
    )


@router.get("/list", response_model=ApiResponse[PageData[KnowledgeMetaResponse]])
async def list_knowledge(
    _: ReadAccess,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    knowledge_type: str | None = None,
    status: str | None = None,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> ApiResponse[PageData[KnowledgeMetaResponse]]:
    items, total = await service.list(
        page=page,
        page_size=page_size,
        knowledge_type=knowledge_type,
        status=status,
    )
    return success_response(
        PageData[KnowledgeMetaResponse].create(
            [KnowledgeMetaResponse.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )
    )


@router.get("/{knowledge_id}", response_model=ApiResponse[KnowledgeMetaResponse])
async def get_knowledge(
    knowledge_id: int,
    _: ReadAccess,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> ApiResponse[KnowledgeMetaResponse]:
    return success_response(
        KnowledgeMetaResponse.model_validate(await service.get(knowledge_id))
    )


@router.put("/{knowledge_id}", response_model=ApiResponse[KnowledgeMetaResponse])
async def update_knowledge(
    knowledge_id: int,
    request: KnowledgeUpdateRequest,
    _: ManageAccess,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> ApiResponse[KnowledgeMetaResponse]:
    return success_response(
        KnowledgeMetaResponse.model_validate(
            await service.update(knowledge_id, request)
        )
    )


@router.delete("/{knowledge_id}", response_model=ApiResponse[KnowledgeMetaResponse])
async def delete_knowledge(
    knowledge_id: int,
    _: ManageAccess,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> ApiResponse[KnowledgeMetaResponse]:
    return success_response(
        KnowledgeMetaResponse.model_validate(await service.delete(knowledge_id))
    )


@router.post(
    "/search",
    response_model=ApiResponse[list[KnowledgeSearchResult]],
)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    _: ReadAccess,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> ApiResponse[list[KnowledgeSearchResult]]:
    results = await service.search(
        query=request.query,
        top_k=request.top_k,
        min_score=request.min_score,
        knowledge_type=request.knowledge_type,
    )
    return success_response(results)
