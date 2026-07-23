from typing import Any


CUSTOMER_ALIASES = {
    "张三": "C001",
    "李四": "C002",
}
PRODUCT_ALIASES = {
    "稳健增利A": "P001",
    "稳健增利债券A": "P001",
}


def resolve_entities(
    message: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict(params)
    if "customer_id" not in resolved:
        for name, entity_id in CUSTOMER_ALIASES.items():
            if name in message:
                resolved["customer_id"] = entity_id
                break
    if "product_id" not in resolved:
        for name, entity_id in PRODUCT_ALIASES.items():
            if name in message:
                resolved["product_id"] = entity_id
                break
    return resolved

