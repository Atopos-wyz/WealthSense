"""应用服务与 Agent 的进程级依赖装配。"""

from __future__ import annotations

from functools import lru_cache

from app.agent import AnalystAgent, CustomerAgent
from app.config import get_settings
from app.dao import get_database_manager
from app.dao.milvus import KnowledgeVectorStore
from app.dao.mysql import ConversationRepository, KnowledgeRepository
from app.service.knowledge import KnowledgeService
from app.service.llm import LanguageModelClient
from app.service.memory import SessionMemoryService
from app.tool.document import DocumentParser
from app.tool.embedding import EmbeddingTool
from app.tool.sql import NL2SQLTool, SQLExecutor, SQLSafetyTool, SQLSchemaProvider


@lru_cache(maxsize=1)
def get_language_model() -> LanguageModelClient:
    return LanguageModelClient(get_settings())


@lru_cache(maxsize=1)
def get_embedding_tool() -> EmbeddingTool:
    settings = get_settings()
    return EmbeddingTool(
        provider=settings.embedding_provider,
        model_name=settings.embedding_model,
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )


@lru_cache(maxsize=1)
def get_knowledge_service() -> KnowledgeService:
    settings = get_settings()
    database = get_database_manager()
    return KnowledgeService(
        repository=KnowledgeRepository(database.mysql),
        vector_store=KnowledgeVectorStore(
            database.milvus,
            dimension=settings.embedding_dimension,
        ),
        parser=DocumentParser(
            chunk_size=settings.knowledge_chunk_size,
            chunk_overlap=settings.knowledge_chunk_overlap,
        ),
        embedding=get_embedding_tool(),
        mysql=database.mysql,
        default_min_score=settings.knowledge_search_min_score,
    )


@lru_cache(maxsize=1)
def get_memory_service() -> SessionMemoryService:
    settings = get_settings()
    database = get_database_manager()
    return SessionMemoryService(
        redis=database.redis,
        archive=ConversationRepository(database.mysql),
        mysql=database.mysql,
        ttl_seconds=settings.session_ttl_seconds,
        max_messages=settings.session_max_messages,
        token_budget=settings.session_token_budget,
    )


@lru_cache(maxsize=1)
def get_customer_agent() -> CustomerAgent:
    return CustomerAgent(
        memory=get_memory_service(),
        knowledge=get_knowledge_service(),
        llm=get_language_model(),
    )


@lru_cache(maxsize=1)
def get_analyst_agent() -> AnalystAgent:
    settings = get_settings()
    database = get_database_manager()
    schema_provider = SQLSchemaProvider(database.mysql)
    return AnalystAgent(
        memory=get_memory_service(),
        redis=database.redis,
        nl2sql=NL2SQLTool(
            llm=get_language_model(),
            schema_provider=schema_provider,
        ),
        executor=SQLExecutor(
            mysql=database.mysql,
            safety=SQLSafetyTool(max_rows=settings.nl2sql_max_rows),
        ),
        llm=get_language_model(),
        cache_ttl_seconds=settings.nl2sql_cache_ttl_seconds,
    )
