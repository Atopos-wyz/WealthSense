"""投顾请求的可解释规则意图路由。"""

from app.models.schemas.advisor import AdvisorChatRequest, AdvisorIntent


INTENT_KEYWORDS: tuple[tuple[AdvisorIntent, tuple[str, ...]], ...] = (
    (
        AdvisorIntent.PRODUCT_COMPARISON,
        ("对比", "比较", "区别", "差异", "哪个更好", "compare"),
    ),
    (
        AdvisorIntent.HOLDING_ANALYSIS,
        ("持仓", "组合", "盈亏", "集中度", "风险暴露", "账户分析"),
    ),
    (
        AdvisorIntent.ASSET_ALLOCATION,
        ("资产配置", "配置比例", "调仓", "再平衡", "仓位分配"),
    ),
    (
        AdvisorIntent.PRODUCT_RECOMMENDATION,
        ("推荐", "买什么", "适合我", "产品", "基金", "理财"),
    ),
)


def classify_intent(request: AdvisorChatRequest) -> AdvisorIntent:
    if request.intent_hint not in (None, AdvisorIntent.UNKNOWN):
        return request.intent_hint
    if len(request.product_ids) >= 2 or request.comparison_customer_ids:
        return AdvisorIntent.PRODUCT_COMPARISON
    normalized = request.message.lower()
    for intent, keywords in INTENT_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return intent
    return AdvisorIntent.UNKNOWN
