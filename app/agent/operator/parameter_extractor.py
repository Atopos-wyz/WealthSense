import re
from decimal import Decimal
from typing import Any

from app.models.schemas.common import OperationIntent

ID_PATTERNS = {
    "customer_id": re.compile(r"\bC[A-Z0-9_-]+\b", re.IGNORECASE),
    "product_id": re.compile(r"\bP[A-Z0-9_-]+\b", re.IGNORECASE),
    "account_id": re.compile(r"\bA[A-Z0-9_-]+\b", re.IGNORECASE),
    "holding_id": re.compile(r"\bH[A-Z0-9_-]+\b", re.IGNORECASE),
    "transaction_id": re.compile(r"\bTX[A-Z0-9_-]+\b", re.IGNORECASE),
}
AMOUNT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(万元|万|元)")
SHARES_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*份")
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def _extract_amount(message: str) -> Decimal | None:
    matches = AMOUNT_PATTERN.findall(message)
    if not matches:
        return None
    value, unit = matches[-1]
    amount = Decimal(value)
    if unit in {"万", "万元"}:
        amount *= Decimal("10000")
    return amount


def extract_parameters(
    message: str,
    intent: OperationIntent,
    known_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = dict(known_params or {})

    for field_name, pattern in ID_PATTERNS.items():
        match = pattern.search(message)
        if match and field_name not in params:
            params[field_name] = match.group(0).upper()

    amount = _extract_amount(message)
    if amount is not None and intent in {
        OperationIntent.PURCHASE,
        OperationIntent.TRANSFER,
    }:
        params.setdefault("amount", amount)

    if intent == OperationIntent.PURCHASE:
        params.setdefault("currency", "CNY")
    elif intent == OperationIntent.REDEEM:
        params.setdefault("redeem_type", "all" if "全部" in message else "partial")
        shares = SHARES_PATTERN.search(message)
        if params["redeem_type"] == "partial" and shares:
            params.setdefault("shares", Decimal(shares.group(1)))
    elif intent == OperationIntent.TRANSFER:
        params.setdefault("currency", "CNY")
        if "account_id" in params:
            params.setdefault("from_account_id", params.pop("account_id"))
    elif intent == OperationIntent.UPDATE_PROFILE:
        phone = PHONE_PATTERN.search(message)
        email = EMAIL_PATTERN.search(message)
        if phone:
            params.setdefault("field_name", "phone")
            params.setdefault("new_value", phone.group(0))
        elif email:
            params.setdefault("field_name", "email")
            params.setdefault("new_value", email.group(0))
    elif intent == OperationIntent.PRODUCT_QUERY:
        params.setdefault("fields", ["name", "status", "net_value"])
    elif intent == OperationIntent.SUSPICIOUS_REPORT:
        params.setdefault("reason", message)
        params.setdefault("evidence_refs", [])
    elif intent == OperationIntent.CREATE_WORK_ORDER:
        params.setdefault("work_order_type", "complaint" if "投诉" in message else "service")
        params.setdefault("description", message)
        params.setdefault("priority", "medium")

    return params
