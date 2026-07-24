# 投顾 Agent 接口与 Redis 事件契约

## 对话接口

普通响应：`POST /api/chat/advisor`

SSE 流式响应：`POST /api/chat/advisor/stream`

请求示例：

```json
{
  "session_id": "session-20260723-001",
  "message": "请推荐适合我的产品",
  "user_id": "user-1001",
  "customer_id": 1001,
  "intent_hint": "PRODUCT_RECOMMENDATION",
  "product_ids": [],
  "comparison_customer_ids": [],
  "top_k": 5
}
```

`intent_hint` 可选值：

- `PRODUCT_RECOMMENDATION`
- `HOLDING_ANALYSIS`
- `ASSET_ALLOCATION`
- `PRODUCT_COMPARISON`
- `UNKNOWN`

普通响应保留需求文档要求的 `reply`、`recommendations`、`reasoning`、
`session_id`，并返回实际意图、路由、分析结果及事件投递回执。

SSE 事件顺序为 `started`、`intent`、零到多条 `recommendation`、
若干 `message` 文本分片、`completed`。异常时发送 `error`。

## Redis Pub/Sub 频道

每个事件同时发布到以下频道：

- `event:all`：全部 Agent 事件。
- `event:type:{event_type}`：按事件类型订阅。
- `event:agent:{target_agent}`：按目标 Agent 定向订阅。

例如画像缺失触发风险测评时，会发布到：

- `event:all`
- `event:type:assessment.required`
- `event:agent:risk`

## 统一事件信封

```json
{
  "event_id": "全局唯一事件ID",
  "event_type": "assessment.required",
  "event_version": "1.0",
  "source_agent": "advisor",
  "target_agents": ["risk"],
  "payload": {
    "reason": "客户画像不存在",
    "requested_action": "START_RISK_ASSESSMENT",
    "callback_event": "assessment.completed"
  },
  "timestamp": "2026-07-23T08:00:00Z",
  "trace_id": "HTTP调用链ID",
  "session_id": "对话会话ID",
  "user_id": "系统用户ID",
  "customer_id": 1001,
  "correlation_id": "跨事件业务关联ID",
  "causation_id": "直接前置事件ID",
  "deduplication_key": "消费者幂等键",
  "metadata": {}
}
```

| 字段 | 必填 | 用途 |
| --- | --- | --- |
| `event_id` | 是 | 全局唯一标识 |
| `event_type` | 是 | 事件路由和业务语义 |
| `event_version` | 是 | 事件结构版本 |
| `source_agent` | 是 | 发布方 |
| `target_agents` | 否 | 定向接收方，空数组表示无定向频道 |
| `payload` | 是 | 事件业务数据 |
| `timestamp` | 是 | UTC 发生时间 |
| `trace_id` | 是 | HTTP、日志与数据库审计链路关联 |
| `session_id` | 否 | 对话会话关联 |
| `user_id` | 否 | 登录用户关联 |
| `customer_id` | 否 | 客户画像关联 |
| `correlation_id` | 否 | 一组业务事件的关联 ID |
| `causation_id` | 否 | 直接触发当前事件的前置事件 |
| `deduplication_key` | 否 | 消费方幂等处理 |
| `metadata` | 否 | 非核心扩展数据 |

## 已实现事件

| 事件 | 发布方 | 主要接收方 | 触发条件 |
| --- | --- | --- | --- |
| `advisor.requested` | Customer | Advisor | 投顾接口收到请求 |
| `advisor.completed` | Advisor | Customer | 投顾流程完成 |
| `advisor.failed` | Advisor | System | 投顾流程异常 |
| `profile.missing` | Advisor | Customer、Risk | 未找到客户画像 |
| `assessment.required` | Advisor | Risk | 缺少有效画像或风险等级 |
| `assessment.completed` | Risk | Advisor、Customer | 风险问卷提交成功 |
| `profile.updated` | System | Advisor、Risk | 画像创建或有效字段更新 |

消费者必须按 `deduplication_key` 做幂等处理，并忽略不支持的更高
`event_version`。Redis 临时不可用不会中断投顾主业务，接口会在
`event_delivery` 中返回失败回执供监控和补偿。
