from enum import StrEnum


class EventChannel(StrEnum):
    OPERATOR_COMMAND = "agent:operator:command"
    OPERATOR_RISK_RESULT = "agent:operator:risk_result"
    OPERATOR_CONTROL = "agent:operator:control"
    RISK_COMMAND = "agent:risk:command"
    AGENT_RESULT = "agent:result"
    TRANSACTION_EVENT = "event:transaction"

