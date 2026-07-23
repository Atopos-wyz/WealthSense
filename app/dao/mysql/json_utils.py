"""MySQL JSON 字段转换。"""

import json
from typing import Any


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def decode_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value
