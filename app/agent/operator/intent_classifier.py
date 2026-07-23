from app.models.schemas.common import OperationIntent


INTENT_KEYWORDS: list[tuple[OperationIntent, tuple[str, ...]]] = [
    (OperationIntent.SUSPICIOUS_REPORT, ("可疑", "上报", "异常交易")),
    (OperationIntent.CREATE_WORK_ORDER, ("工单", "投诉", "报修")),
    (OperationIntent.RISK_REASSESSMENT, ("风险测评", "风评", "重新测评")),
    (OperationIntent.UPDATE_PROFILE, ("修改手机号", "更新手机号", "修改地址", "修改邮箱")),
    (OperationIntent.PRODUCT_QUERY, ("产品查询", "产品详情", "最新净值", "查询产品")),
    (OperationIntent.REDEEM, ("赎回", "卖出")),
    (OperationIntent.TRANSFER, ("转账", "划转")),
    (OperationIntent.PURCHASE, ("申购", "购买", "买入")),
]


def classify_intent(message: str) -> OperationIntent:
    normalized = message.strip().lower()
    for intent, keywords in INTENT_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return intent
    return OperationIntent.UNKNOWN

