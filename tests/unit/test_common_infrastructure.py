from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from io import StringIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.settings import Settings
from app.dao import DatabaseManager
from app.models.error_codes import ErrorCode
from app.models.schemas import Permission, UserRole
from app.utils.exception_handlers import register_exception_handlers
from app.utils.exceptions import AuthenticationError, PermissionDeniedError
from app.utils.logger import JsonFormatter, reset_trace_id, set_trace_id
from app.utils.permissions import create_access_token, decode_access_token
from app.view.response import failure_response, success_response


def build_settings(**overrides) -> Settings:
    values = {
        "mysql_password": "mysql-secret",
        "redis_password": "redis-secret",
        "neo4j_password": "neo4j-secret",
        "milvus_root_password": "milvus-secret",
        "jwt_secret_key": "test-jwt-secret-with-enough-entropy",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_hide_secrets_and_validate_production_secret() -> None:
    settings = build_settings()
    assert "mysql-secret" not in repr(settings)
    assert settings.milvus_uri == "http://127.0.0.1:19530"

    with pytest.raises(ValidationError):
        build_settings(
            app_env="production",
            jwt_secret_key="development-only-change-me",
        )


def test_database_manager_is_lazy_and_closable_without_connections() -> None:
    manager = DatabaseManager(build_settings())

    assert not manager.mysql.connected
    assert not manager.redis.connected
    assert not manager.neo4j.connected
    assert not manager.milvus.connected

    asyncio.run(manager.close_all())


def test_unified_response_envelope_and_error_code() -> None:
    success = success_response({"value": 1}, trace_id="trace-success")
    failure = failure_response(
        ErrorCode.FORBIDDEN,
        details={"permission": "operation:execute"},
        trace_id="trace-failure",
    )

    assert success.model_dump(mode="json") == {
        "code": 200,
        "message": "success",
        "data": {"value": 1},
        "trace_id": "trace-success",
    }
    assert failure.code == ErrorCode.FORBIDDEN
    assert failure.data == {"details": {"permission": "operation:execute"}}


def test_json_logger_contains_trace_id() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("wealthsense-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    token = set_trace_id("trace-logger")
    try:
        logger.info("hello")
    finally:
        reset_trace_id(token)

    payload = json.loads(stream.getvalue())
    assert payload["message"] == "hello"
    assert payload["trace_id"] == "trace-logger"


def test_mock_jwt_and_role_permissions() -> None:
    settings = build_settings()
    token = create_access_token(
        subject="user-1",
        roles=[UserRole.CUSTOMER_MANAGER],
        settings=settings,
    )
    user = decode_access_token(token, settings=settings)

    assert user.user_id == "user-1"
    assert user.has_role(UserRole.CUSTOMER_MANAGER)
    assert user.has_permission(Permission.OPERATION_EXECUTE)
    assert not user.has_permission(Permission.RISK_HANDLE)


def test_expired_token_maps_to_public_error_code() -> None:
    settings = build_settings()
    token = create_access_token(
        subject="user-1",
        roles=[UserRole.CUSTOMER],
        expires_delta=timedelta(seconds=-1),
        settings=settings,
    )

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token, settings=settings)
    assert exc_info.value.code == ErrorCode.TOKEN_EXPIRED


def test_exception_handler_uses_unified_response() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/protected")
    async def protected() -> None:
        raise PermissionDeniedError()

    client = TestClient(app)
    response = client.get("/protected")
    payload = response.json()

    assert response.status_code == 403
    assert payload["code"] == 403
    assert payload["message"] == "无权执行该操作"
    assert payload["trace_id"]
