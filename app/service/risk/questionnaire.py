"""模拟风险评估问卷。

16 道题覆盖收入与资产、投资经验、风险承受力和投资目标四个维度。
每个选项使用 0/33/67/100 的标准分，最终分数取 16 题平均值。
"""

from decimal import Decimal

from app.models.schemas.risk import (
    QuestionOption,
    QuestionnaireResponse,
    RiskDimension,
    RiskQuestion,
)


def _options(a: str, b: str, c: str, d: str) -> list[QuestionOption]:
    return [
        QuestionOption(code="A", text=a, score=Decimal("0")),
        QuestionOption(code="B", text=b, score=Decimal("33")),
        QuestionOption(code="C", text=c, score=Decimal("67")),
        QuestionOption(code="D", text=d, score=Decimal("100")),
    ]


QUESTIONS: tuple[RiskQuestion, ...] = (
    RiskQuestion(
        id=1,
        dimension=RiskDimension.BASIC_CAPACITY,
        text="您的家庭年可支配收入大致为？",
        options=_options("5万元以下", "5万—20万元", "20万—50万元", "50万元以上"),
    ),
    RiskQuestion(
        id=2,
        dimension=RiskDimension.BASIC_CAPACITY,
        text="您的主要收入来源稳定程度如何？",
        options=_options("目前无稳定收入", "收入波动较大", "收入较稳定", "收入稳定且来源多元"),
    ),
    RiskQuestion(
        id=3,
        dimension=RiskDimension.BASIC_CAPACITY,
        text="扣除日常开支和负债后，可用于投资的资产规模为？",
        options=_options("1万元以下", "1万—10万元", "10万—100万元", "100万元以上"),
    ),
    RiskQuestion(
        id=4,
        dimension=RiskDimension.BASIC_CAPACITY,
        text="未来一年需要动用这笔投资资金的比例约为？",
        options=_options("超过75%", "50%—75%", "25%—50%", "低于25%"),
    ),
    RiskQuestion(
        id=5,
        dimension=RiskDimension.INVESTMENT_EXPERIENCE,
        text="您的证券或理财投资年限为？",
        options=_options("没有经验", "不足3年", "3—5年", "5年以上"),
    ),
    RiskQuestion(
        id=6,
        dimension=RiskDimension.INVESTMENT_EXPERIENCE,
        text="您曾实际投资过的产品中，风险最高的是？",
        options=_options("存款或货币基金", "债券或低风险理财", "混合基金或股票基金", "期权、期货或高风险私募"),
    ),
    RiskQuestion(
        id=7,
        dimension=RiskDimension.INVESTMENT_EXPERIENCE,
        text="您对净值波动、回撤和分散投资的理解程度是？",
        options=_options("不了解", "了解少量基础概念", "能够理解并用于决策", "能够独立分析复杂产品风险"),
    ),
    RiskQuestion(
        id=8,
        dimension=RiskDimension.INVESTMENT_EXPERIENCE,
        text="过去一年您的投资交易频率大致为？",
        options=_options("没有交易", "每季度少于1次", "每月1—3次", "每周1次或更多"),
    ),
    RiskQuestion(
        id=9,
        dimension=RiskDimension.RISK_TOLERANCE,
        text="若投资在一个月内下跌10%，您通常会如何处理？",
        options=_options("立即全部卖出", "卖出大部分", "继续持有观察", "在评估后考虑追加"),
    ),
    RiskQuestion(
        id=10,
        dimension=RiskDimension.RISK_TOLERANCE,
        text="在不影响生活的前提下，您能接受的最大年度亏损是？",
        options=_options("不能接受亏损", "不超过5%", "不超过15%", "可接受30%及以上"),
    ),
    RiskQuestion(
        id=11,
        dimension=RiskDimension.RISK_TOLERANCE,
        text="收益不确定时，您更愿意选择哪种组合？",
        options=_options("本金安全，收益很低", "小幅波动，收益略高", "中等波动，争取较高收益", "高波动，追求高收益"),
    ),
    RiskQuestion(
        id=12,
        dimension=RiskDimension.RISK_TOLERANCE,
        text="对于单一资产集中持仓，您的态度是？",
        options=_options("完全避免", "仅接受很小比例", "充分研究后可接受一定比例", "愿意集中持仓获取超额收益"),
    ),
    RiskQuestion(
        id=13,
        dimension=RiskDimension.INVESTMENT_GOAL,
        text="您的首要投资目标是？",
        options=_options("保住本金", "稳健增值", "长期资本增值", "短期获取较高收益"),
    ),
    RiskQuestion(
        id=14,
        dimension=RiskDimension.INVESTMENT_GOAL,
        text="您计划持有本次投资多长时间？",
        options=_options("不足1年", "1—3年", "3—5年", "5年以上"),
    ),
    RiskQuestion(
        id=15,
        dimension=RiskDimension.INVESTMENT_GOAL,
        text="您期望的年化收益水平大致为？",
        options=_options("接近存款收益", "3%—5%", "5%—10%", "10%以上并接受相应风险"),
    ),
    RiskQuestion(
        id=16,
        dimension=RiskDimension.INVESTMENT_GOAL,
        text="对于杠杆或结构复杂的投资产品，您的态度是？",
        options=_options("完全不考虑", "了解后仍倾向不参与", "小比例尝试", "理解风险后可以配置"),
    ),
)


def get_questionnaire() -> QuestionnaireResponse:
    return QuestionnaireResponse(
        version="WS-RISK-2026.1",
        title="WealthSense 投资者风险承受能力问卷",
        total_questions=len(QUESTIONS),
        scoring_rule="每题标准分为0/33/67/100，总分取16题平均值并映射C1-C5",
        questions=list(QUESTIONS),
    )
