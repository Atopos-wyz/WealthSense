import unittest

from app.agent.operator.intent_classifier import classify_intent
from app.models.schemas.common import OperationIntent


class IntentClassifierTests(unittest.TestCase):
    def test_all_eight_intents(self) -> None:
        cases = {
            "帮张三申购10万元产品": OperationIntent.PURCHASE,
            "把这个产品全部赎回": OperationIntent.REDEEM,
            "转账6万元": OperationIntent.TRANSFER,
            "重新进行风险测评": OperationIntent.RISK_REASSESSMENT,
            "修改手机号为13800138000": OperationIntent.UPDATE_PROFILE,
            "查询产品最新净值": OperationIntent.PRODUCT_QUERY,
            "上报这笔可疑交易": OperationIntent.SUSPICIOUS_REPORT,
            "创建一个投诉工单": OperationIntent.CREATE_WORK_ORDER,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify_intent(message), expected)

    def test_unknown_intent(self) -> None:
        self.assertEqual(classify_intent("今天天气不错"), OperationIntent.UNKNOWN)

