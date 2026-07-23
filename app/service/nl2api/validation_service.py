import hashlib
import json
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.models.schemas.common import OperationIntent
from app.models.schemas.operation import OPERATION_PARAM_MODELS
from app.utils.exceptions import OperatorError


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported value: {type(value)!r}")


def hash_params(params: dict[str, Any]) -> str:
    serialized = json.dumps(
        params,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_operation_params(
    intent: OperationIntent,
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    model_type = OPERATION_PARAM_MODELS.get(intent)
    if model_type is None:
        raise OperatorError(
            "OP_INTENT_UNKNOWN",
            "无法识别业务操作意图",
        )
    try:
        model = model_type.model_validate(params)
    except ValidationError as exc:
        missing_fields = [
            str(error["loc"][0])
            for error in exc.errors()
            if error["type"] == "missing"
        ]
        if missing_fields:
            return params, sorted(set(missing_fields))
        raise OperatorError(
            "OP_PARAM_INVALID",
            "业务参数格式不正确",
            details={"validation_errors": exc.errors(include_url=False)},
        ) from exc
    return model.model_dump(mode="json"), []
