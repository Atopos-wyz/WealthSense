import time
import unittest

from app.models.schemas.common import AgentEvent, AgentId
from app.utils.exceptions import PermissionDeniedError
from app.utils.security import (
    decode_hs256_jwt,
    encode_hs256_jwt,
    sign_agent_event,
    verify_agent_event,
)


class SecurityTests(unittest.TestCase):
    def test_jwt_requires_valid_signature_and_claims(self) -> None:
        token = encode_hs256_jwt(
            {
                "sub": "EMP001",
                "role": "advisor",
                "organization_id": "ORG001",
                "customer_ids": ["C001"],
                "iss": "wealthsense",
                "exp": int(time.time()) + 60,
            },
            "correct-secret",
        )
        claims = decode_hs256_jwt(token, "correct-secret", "wealthsense")
        self.assertEqual(claims["sub"], "EMP001")
        with self.assertRaises(PermissionDeniedError):
            decode_hs256_jwt(token, "wrong-secret", "wealthsense")

    def test_agent_source_cannot_be_changed_after_signing(self) -> None:
        event = AgentEvent(
            event_id="EVT001",
            event_type="operation.requested",
            source_agent=AgentId.ADVISOR,
            target_agents=[AgentId.OPERATOR],
        )
        signed = sign_agent_event(event, "advisor-secret")
        forged = signed.model_copy(update={"source_agent": AgentId.RISK})
        with self.assertRaises(PermissionDeniedError):
            verify_agent_event(forged, "risk-secret")
