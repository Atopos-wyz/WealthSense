import unittest

from app.models.schemas.common import OperationStatus
from app.service.nl2api.state_machine import (
    InvalidStateTransition,
    assert_transition,
)


class StateMachineTests(unittest.TestCase):
    def test_normal_transition(self) -> None:
        assert_transition(
            OperationStatus.WAITING_RISK_REVIEW,
            OperationStatus.RISK_APPROVED,
        )

    def test_cannot_skip_risk_review(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            assert_transition(
                OperationStatus.VALIDATING,
                OperationStatus.EXECUTING,
            )

