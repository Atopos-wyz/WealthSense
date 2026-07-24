"""投顾四类业务流程：推荐、持仓、配置与对比。"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.mysql.advisor_dao import AdvisorDAO
from app.models.schemas.advisor import (
    AllocationItem,
    AssetAllocationAdvice,
    ComparisonItem,
    ComparisonReport,
    HoldingAnalysis,
    ProductRiskLevel,
    ProductRecommendation,
)
from app.models.schemas.common import RiskLevel
from app.tool.graph import AdvisorGraphTool


ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_PLACES = Decimal("0.01")
RISK_RANK = {
    **{level.value: index for index, level in enumerate(RiskLevel, 1)},
    **{f"R{index}": index for index in range(1, 6)},
}

ALLOCATION_TARGETS: dict[RiskLevel, dict[str, Decimal]] = {
    RiskLevel.C1: {
        "现金类": Decimal("25"),
        "固收类": Decimal("65"),
        "权益类": Decimal("5"),
        "另类": Decimal("5"),
    },
    RiskLevel.C2: {
        "现金类": Decimal("15"),
        "固收类": Decimal("55"),
        "权益类": Decimal("20"),
        "另类": Decimal("10"),
    },
    RiskLevel.C3: {
        "现金类": Decimal("10"),
        "固收类": Decimal("40"),
        "权益类": Decimal("40"),
        "另类": Decimal("10"),
    },
    RiskLevel.C4: {
        "现金类": Decimal("5"),
        "固收类": Decimal("25"),
        "权益类": Decimal("55"),
        "另类": Decimal("15"),
    },
    RiskLevel.C5: {
        "现金类": Decimal("5"),
        "固收类": Decimal("10"),
        "权益类": Decimal("65"),
        "另类": Decimal("20"),
    },
}

ASSET_TYPE_ALIASES = {
    "cash": "现金类",
    "现金": "现金类",
    "现金类": "现金类",
    "fixed_income": "固收类",
    "bond": "固收类",
    "债券": "固收类",
    "固收": "固收类",
    "固收类": "固收类",
    "equity": "权益类",
    "stock": "权益类",
    "股票": "权益类",
    "权益": "权益类",
    "权益类": "权益类",
    "alternative": "另类",
    "另类": "另类",
}


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    return Decimal(str(value))


def _ratio(value: Decimal, total: Decimal) -> Decimal:
    if total <= 0:
        return ZERO
    return (value / total * HUNDRED).quantize(
        TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


class AdvisorService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        graph_tool: AdvisorGraphTool | None = None,
    ) -> None:
        self.session = session
        self.dao = AdvisorDAO(session)
        self.graph_tool = graph_tool or AdvisorGraphTool()

    async def recommend_products(
        self,
        *,
        customer_id: int,
        profile: dict[str, Any],
        top_k: int,
        trace_id: str,
    ) -> tuple[list[ProductRecommendation], list[str]]:
        risk_level = str(profile["risk_level"])
        candidates = await self.dao.list_suitable_products(
            risk_level,
            limit=max(top_k * 10, 30),
        )
        graph_context = await self.graph_tool.enrich_products(
            [int(product["id"]) for product in candidates]
        )
        preferences = self._preference_values(
            profile.get("product_preference", {})
        )
        scored = [
            (
                self._product_score(product, risk_level, preferences),
                product,
            )
            for product in candidates
        ]
        scored.sort(key=lambda item: (-item[0], int(item[1]["id"])))
        selected = [product for _, product in scored[:top_k]]

        await self.dao.record_suitability_checks(
            customer_id=customer_id,
            customer_risk_level=risk_level,
            products=selected,
            trace_id=trace_id,
        )
        await self.session.commit()

        recommendations = [
            self._recommendation(
                product,
                score,
                risk_level,
                preferences,
                graph_context.get(int(product["id"]), {}),
            )
            for score, product in scored[:top_k]
        ]
        reasoning = [
            f"先按适当性规则过滤：仅保留风险等级不高于客户 {risk_level} 的产品",
            "结合预期收益、期限流动性、客户偏好和风险等级接近度进行排序",
        ]
        if graph_context:
            reasoning.append("已使用 Neo4j 的行业、市场和基金经理关系增强推荐理由")
        else:
            reasoning.append("图谱暂不可用，本次使用 MySQL 产品属性完成降级排序")
        return recommendations, reasoning

    async def analyze_holdings(
        self,
        *,
        customer_id: int,
        customer_risk_level: str,
    ) -> tuple[HoldingAnalysis, list[str]]:
        holdings = await self.dao.list_holdings(customer_id)
        graph_paths = await self.graph_tool.holding_paths(customer_id)
        total_value = sum(
            (_decimal(item["current_value"]) for item in holdings),
            ZERO,
        )
        total_profit_loss = sum(
            (_decimal(item["profit_loss"]) for item in holdings),
            ZERO,
        )
        product_values: dict[str, Decimal] = defaultdict(Decimal)
        industry_values: dict[str, Decimal] = defaultdict(Decimal)
        risk_values: dict[str, Decimal] = defaultdict(Decimal)
        warnings: list[str] = []

        for holding in holdings:
            value = _decimal(holding["current_value"])
            product_values[str(holding["product_name"])] += value
            industry_values[str(holding.get("industry") or "未分类")] += value
            risk_values[str(holding["risk_level"])] += value

        product_ratio = {
            name: _ratio(value, total_value)
            for name, value in product_values.items()
        }
        industry_ratio = {
            name: _ratio(value, total_value)
            for name, value in industry_values.items()
        }
        risk_ratio = {
            name: _ratio(value, total_value)
            for name, value in risk_values.items()
        }
        for name, ratio in product_ratio.items():
            if ratio >= Decimal("40"):
                warnings.append(f"单一产品“{name}”占比 {ratio}%，集中度偏高")
        for name, ratio in industry_ratio.items():
            if name != "未分类" and ratio >= Decimal("50"):
                warnings.append(f"行业“{name}”占比 {ratio}%，行业暴露偏高")
        excessive = [
            level
            for level in risk_ratio
            if RISK_RANK.get(level, 99)
            > RISK_RANK.get(customer_risk_level, 0)
        ]
        if excessive:
            warnings.append(
                "存在高于客户风险承受等级的持仓：" + "、".join(excessive)
            )
        if not holdings:
            warnings.append("当前未查询到有效持仓，无法进行集中度分析")

        analysis = HoldingAnalysis(
            total_value=total_value,
            total_profit_loss=total_profit_loss,
            holding_count=len(holdings),
            product_concentration=product_ratio,
            industry_concentration=industry_ratio,
            risk_exposure=risk_ratio,
            warnings=warnings,
        )
        reasoning = [
            "穿透客户有效持仓并按产品、行业和风险等级聚合当前市值",
            "单一产品达到 40% 或单一行业达到 50% 时提示集中度风险",
        ]
        if graph_paths:
            reasoning.append("Neo4j 客户—持仓—产品—行业路径已用于关系校验")
        return analysis, reasoning

    def allocate_assets(
        self,
        profile: dict[str, Any],
    ) -> tuple[AssetAllocationAdvice, list[str]]:
        risk_level = RiskLevel(str(profile["risk_level"]))
        target = ALLOCATION_TARGETS[risk_level]
        current: dict[str, Decimal] = defaultdict(Decimal)
        for name, value in (profile.get("asset_allocation") or {}).items():
            normalized = ASSET_TYPE_ALIASES.get(str(name).lower(), str(name))
            current[normalized] += _decimal(value)

        items: list[AllocationItem] = []
        for asset_type, target_ratio in target.items():
            current_ratio = current.get(asset_type, ZERO)
            adjustment = (target_ratio - current_ratio).quantize(TWO_PLACES)
            if adjustment > 0:
                suggestion = f"建议增加约 {adjustment}%"
            elif adjustment < 0:
                suggestion = f"建议降低约 {abs(adjustment)}%"
            else:
                suggestion = "当前比例与模型目标一致"
            items.append(
                AllocationItem(
                    asset_type=asset_type,
                    current_ratio=current_ratio,
                    target_ratio=target_ratio,
                    adjustment=adjustment,
                    suggestion=suggestion,
                )
            )
        advice = AssetAllocationAdvice(
            risk_level=risk_level,
            items=items,
            summary=(
                f"基于 {risk_level.value} 风险等级给出战略配置比例；"
                "执行前仍需结合投资期限、流动性需求及市场变化复核。"
            ),
        )
        return advice, [
            f"从客户画像提取有效风险标签 {risk_level.value}",
            "匹配风险等级对应的战略资产配置模型",
            "以当前配置和目标配置的差额生成调仓方向",
        ]

    async def compare(
        self,
        *,
        product_ids: list[int],
        customer_ids: list[int],
    ) -> tuple[ComparisonReport, list[str]]:
        products = await self.dao.get_products(product_ids)
        comparisons = [
            ComparisonItem(
                product_id=int(product["id"]),
                product_name=str(product["product_name"]),
                risk_level=ProductRiskLevel(str(product["risk_level"])),
                expected_return=product.get("expected_return"),
                term_days=int(product.get("term_days") or 0),
                min_amount=_decimal(product.get("min_amount")),
                differences=self._product_differences(product, products),
            )
            for product in products
        ]
        holding_rows = await self.dao.list_customer_holdings(customer_ids)
        customer_summaries = self._customer_summaries(
            customer_ids,
            holding_rows,
        )
        if comparisons and customer_summaries:
            conclusion = "已完成产品属性及客户持仓结构的联合差异对比"
        elif comparisons:
            conclusion = "已完成产品风险、收益、期限和起投金额对比"
        elif customer_summaries:
            conclusion = "已完成多客户持仓规模、收益和产品数量对比"
        else:
            conclusion = "未找到可用于对比的数据，请提供有效产品或客户 ID"
        report = ComparisonReport(
            products=comparisons,
            customer_summaries=customer_summaries,
            conclusion=conclusion,
        )
        return report, [
            "按请求 ID 查询产品集合与客户持仓集合",
            "对产品风险、收益、期限及客户集中度进行结构化差异计算",
        ]

    @staticmethod
    def _preference_values(raw: Any) -> set[str]:
        if not isinstance(raw, dict):
            return set()
        values: set[str] = set()
        for item in raw.values():
            if isinstance(item, list):
                values.update(str(value).lower() for value in item)
            elif item is not None:
                values.add(str(item).lower())
        return values

    @staticmethod
    def _product_score(
        product: dict[str, Any],
        customer_risk_level: str,
        preferences: set[str],
    ) -> Decimal:
        risk_gap = max(
            0,
            RISK_RANK[customer_risk_level]
            - RISK_RANK[str(product["risk_level"])],
        )
        risk_score = Decimal(max(0, 40 - risk_gap * 8))
        expected_return = max(ZERO, _decimal(product.get("expected_return")))
        return_score = min(Decimal("20"), expected_return * Decimal("2"))
        term_days = int(product.get("term_days") or 0)
        liquidity_score = Decimal(max(0, 15 - min(term_days, 1095) / 73))
        attributes = {
            str(product.get("product_type") or "").lower(),
            str(product.get("industry") or "").lower(),
            str(product.get("market") or "").lower(),
        }
        preference_score = Decimal("25") if preferences & attributes else ZERO
        return (risk_score + return_score + liquidity_score + preference_score).quantize(
            TWO_PLACES,
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _recommendation(
        product: dict[str, Any],
        score: Decimal,
        customer_risk_level: str,
        preferences: set[str],
        graph_context: dict[str, Any],
    ) -> ProductRecommendation:
        reasons = [
            f"风险等级 {product['risk_level']} 不高于客户 {customer_risk_level}",
        ]
        if product.get("expected_return") is not None:
            reasons.append(f"预期年化收益率约 {product['expected_return']}%")
        if product.get("term_days"):
            reasons.append(f"期限 {product['term_days']} 天")
        attributes = {
            str(product.get("product_type") or "").lower(),
            str(product.get("industry") or "").lower(),
            str(product.get("market") or "").lower(),
        }
        if preferences & attributes:
            reasons.append("与已确认产品偏好匹配")
        if graph_context:
            reasons.append("已结合图谱行业、市场及管理人关系")
        return ProductRecommendation(
            product_id=int(product["id"]),
            product_code=str(product["product_code"]),
            product_name=str(product["product_name"]),
            product_type=str(product["product_type"]),
            risk_level=ProductRiskLevel(str(product["risk_level"])),
            expected_return=product.get("expected_return"),
            min_amount=_decimal(product.get("min_amount")),
            term_days=int(product.get("term_days") or 0),
            fund_manager=product.get("fund_manager"),
            industry=product.get("industry"),
            market=product.get("market"),
            score=score,
            reason="；".join(reasons),
            graph_context=graph_context,
        )

    @staticmethod
    def _product_differences(
        product: dict[str, Any],
        products: list[dict[str, Any]],
    ) -> list[str]:
        if len(products) <= 1:
            return ["缺少其他产品，暂不能形成相对差异"]
        differences: list[str] = []
        returns = [
            _decimal(item.get("expected_return"))
            for item in products
            if item.get("expected_return") is not None
        ]
        if returns and product.get("expected_return") is not None:
            value = _decimal(product["expected_return"])
            if value == max(returns):
                differences.append("预期收益率在对比产品中最高")
            if value == min(returns):
                differences.append("预期收益率在对比产品中最低")
        terms = [int(item.get("term_days") or 0) for item in products]
        if int(product.get("term_days") or 0) == min(terms):
            differences.append("期限最短，流动性相对更好")
        risks = [RISK_RANK[str(item["risk_level"])] for item in products]
        if RISK_RANK[str(product["risk_level"])] == min(risks):
            differences.append("风险等级最低")
        return differences or ["各核心指标处于对比集合中间水平"]

    @staticmethod
    def _customer_summaries(
        customer_ids: list[int],
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[int(row["customer_id"])].append(row)
        summaries = []
        for customer_id in customer_ids:
            holdings = grouped.get(customer_id, [])
            total_value = sum(
                (_decimal(row["current_value"]) for row in holdings),
                ZERO,
            )
            total_profit = sum(
                (_decimal(row["profit_loss"]) for row in holdings),
                ZERO,
            )
            summaries.append(
                {
                    "customer_id": customer_id,
                    "total_value": float(total_value),
                    "total_profit_loss": float(total_profit),
                    "product_count": len(holdings),
                }
            )
        return summaries
