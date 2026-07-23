"""本地演通路演脚本：python -m tests.fixtures.run_risk_demo [场景名]

示例：
  python -m tests.fixtures.run_risk_demo
  python -m tests.fixtures.run_risk_demo multi_rule_combo
  python -m tests.fixtures.run_risk_demo --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore
from app.event.publisher import InMemoryEventPublisher
from app.service.risk.alert_service import RiskAlertService
from app.service.risk.handle_service import RiskHandleService
from app.service.risk.monitor_service import RiskMonitorService
from app.service.risk.reason_llm import ReasonLlmService
from tests.fixtures.risk_demo_scenarios import (
    DEFAULT_DEMO_SCENARIO,
    get_scenario,
    list_scenario_names,
)


async def run_story(scenario_name: str) -> int:
    memory = InMemoryEventPublisher()
    store = InMemoryRiskAlertStore()
    monitor = RiskMonitorService(
        store=store,
        publisher=memory,
        memory_publisher=memory,
        llm=ReasonLlmService(mode="mock"),
    )
    alerts = RiskAlertService(store)
    handle = RiskHandleService(store)

    request = get_scenario(scenario_name)
    print(f"=== 演示场景: {scenario_name} ===")
    print(f"客户: {request.customer_id}  金额: {request.amount}")

    result = await monitor.monitor(request)
    print("\n[1] monitor 结果")
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )

    if result.alert_id is None:
        print("\n无预警记录，故事结束。")
        return 0

    detail = await alerts.get_public(result.alert_id)
    print("\n[2] 查询预警（字段白名单）")
    print(json.dumps(detail, ensure_ascii=False, indent=2))

    if result.broadcasted and memory.published:
        print("\n[3] 广播事件 event:risk_alert")
        print(json.dumps(memory.published[0][1], ensure_ascii=False, indent=2))
    else:
        print("\n[3] 未广播（低风险或审计样例）")

    if result.hit:
        confirmed = await handle.handle(result.alert_id, "已确认")
        print("\n[4] 专员处置 → 已确认")
        print(json.dumps(confirmed, ensure_ascii=False, indent=2))

    print("\n=== 3 分钟 AML 故事链路完成 ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WealthSense 风控演示路演")
    parser.add_argument(
        "scenario",
        nargs="?",
        default=DEFAULT_DEMO_SCENARIO,
        help=f"场景名，默认 {DEFAULT_DEMO_SCENARIO}",
    )
    parser.add_argument("--list", action="store_true", help="列出全部场景")
    args = parser.parse_args(argv)

    if args.list:
        print("可用场景:")
        for name in list_scenario_names():
            mark = " (默认)" if name == DEFAULT_DEMO_SCENARIO else ""
            print(f"  - {name}{mark}")
        return 0

    try:
        return asyncio.run(run_story(args.scenario))
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
