import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.models.schemas.common import AgentEvent
from app.utils.exceptions import PermissionDeniedError


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_hs256_jwt(
    token: str,
    secret: str,
    issuer: str,
) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(
            secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        supplied = _b64url_decode(signature_part)
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid signature")
        header = json.loads(_b64url_decode(header_part))
        payload = json.loads(_b64url_decode(payload_part))
        if header.get("alg") != "HS256":
            raise ValueError("unsupported algorithm")
        if payload.get("iss") != issuer:
            raise ValueError("invalid issuer")
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise ValueError("token expired")
        for claim in ("sub", "role", "organization_id"):
            if not payload.get(claim):
                raise ValueError(f"missing claim: {claim}")
        for scope_claim in (
            "customer_ids",
            "account_ids",
            "holding_ids",
        ):
            if not isinstance(payload.get(scope_claim, []), list):
                raise ValueError(f"{scope_claim} must be a list")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise PermissionDeniedError(
            "OP_AUTH_INVALID",
            "身份令牌无效或已过期",
        ) from exc


def encode_hs256_jwt(
    claims: dict[str, Any],
    secret: str,
) -> str:
    header = _b64url_encode(
        json.dumps(
            {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    payload = _b64url_encode(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64url_encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def sign_agent_event(event: AgentEvent, secret: str) -> AgentEvent:
    unsigned = event.model_copy(update={"signature": None})
    serialized = json.dumps(
        unsigned.model_dump(mode="json", exclude={"signature"}),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        serialized,
        hashlib.sha256,
    ).hexdigest()
    return event.model_copy(update={"signature": signature})


def verify_agent_event(event: AgentEvent, secret: str) -> None:
    if not event.signature:
        raise PermissionDeniedError(
            "OP_EVENT_SIGNATURE_INVALID",
            "Agent事件缺少签名",
        )
    expected = sign_agent_event(
        event.model_copy(update={"signature": None}),
        secret,
    ).signature
    if not hmac.compare_digest(expected or "", event.signature):
        raise PermissionDeniedError(
            "OP_EVENT_SIGNATURE_INVALID",
            "Agent事件签名无效",
        )
