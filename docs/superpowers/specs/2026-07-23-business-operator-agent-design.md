# WealthSense 业务操作 Agent 设计

日期：2026-07-23  
状态：已完成对话评审，等待书面确认  
范围：仅实现业务操作 Agent；其他 Agent 由其他成员实现

## 1. 目标

业务操作 Agent 将 HTTP 请求或其他 Agent 发布的 Redis 事件转换为受控业务操作。它负责八类意图的理解、参数提取、实体解析、权限、操作状态、二次确认、幂等、Mock API 调用、审计和事件反馈。

风控判断不在业务操作 Agent 内实现。每次可执行操作都必须通过 Redis 向风控 Agent 发起审核，并等待风控 Agent 发布结果。未收到有效的风控通过结果时，业务操作 Agent不得执行。

八类操作：

1. 产品申购；
2. 产品赎回；
3. 转账；
4. 风险测评重做；
5. 客户信息更新；
6. 产品查询；
7. 可疑交易上报；
8. 工单创建。

## 2. 架构选择

采用现有项目的 MVC + Agent + Service + Tool + DAO 结构：

```text
View
→ API Controller
→ Business Operator Agent
→ Operation Service
→ Tool / DAO
→ MySQL / Redis / Mock API
```

Redis Pub/Sub 用于 Agent 间异步通信；MySQL 是操作状态、确认、风控结果、幂等和审计的权威存储。

## 3. 目录设计

```text
app/
├── api/operation/
│   ├── __init__.py
│   ├── routes.py
│   └── dependencies.py
├── agent/operator/
│   ├── __init__.py
│   ├── agent.py
│   ├── intent_classifier.py
│   ├── parameter_extractor.py
│   ├── entity_resolver.py
│   └── prompts.py
├── models/entities/
│   ├── operation.py
│   ├── operation_version.py
│   ├── risk_review.py
│   ├── confirmation.py
│   ├── execution_attempt.py
│   ├── audit_log.py
│   └── processed_event.py
├── models/schemas/
│   ├── common.py
│   ├── operation.py
│   ├── purchase.py
│   ├── redeem.py
│   ├── transfer.py
│   ├── profile_update.py
│   ├── risk_assessment.py
│   ├── product_query.py
│   ├── suspicious_report.py
│   └── workorder.py
├── service/nl2api/
│   ├── operation_service.py
│   ├── permission_service.py
│   ├── validation_service.py
│   ├── risk_review_service.py
│   ├── confirmation_service.py
│   ├── idempotency_service.py
│   └── state_machine.py
├── tool/operation/
│   ├── registry.py
│   ├── purchase_tool.py
│   ├── redeem_tool.py
│   ├── transfer_tool.py
│   ├── profile_tool.py
│   ├── risk_assessment_tool.py
│   ├── product_query_tool.py
│   ├── suspicious_report_tool.py
│   ├── workorder_tool.py
│   └── mock/
├── dao/mysql/
│   ├── operation_repository.py
│   ├── customer_repository.py
│   ├── product_repository.py
│   └── account_repository.py
├── dao/redis/
│   ├── redis_client.py
│   ├── confirmation_store.py
│   ├── idempotency_store.py
│   ├── event_publisher.py
│   └── event_subscriber.py
├── event/
│   ├── channels.py
│   ├── schemas.py
│   ├── publisher.py
│   ├── subscriber.py
│   ├── event_router.py
│   └── handlers/
│       ├── operation_request_handler.py
│       ├── risk_result_handler.py
│       └── control_event_handler.py
├── config/
│   ├── settings.py
│   ├── database.py
│   └── redis.py
└── utils/
    ├── exceptions.py
    ├── ids.py
    └── logging.py
```

调用方向必须保持单向：

```text
API / Redis Subscriber
→ Agent
→ Service
→ Tool / DAO
→ 外部系统
```

API 不直接写数据库，Agent 不直接执行 SQL，Tool 不处理 HTTP，DAO 不反向调用 Agent。

## 4. 双入口

业务操作 Agent 支持两个入口，最终进入同一个 `OperationService`：

### 4.1 HTTP入口

```http
POST /api/operation/chat
POST /api/operation/{operation_id}/confirm
POST /api/operation/{operation_id}/cancel
GET  /api/operation/{operation_id}
```

### 4.2 Redis事件入口

业务操作 Agent 订阅：

```text
agent:operator:command
agent:operator:risk_result
agent:operator:control
```

其他 Agent 通过 `operation.requested` 请求八类业务操作。业务操作 Agent 不直接信任来源 Agent 提供的权限、风控或实体结论，必须重新完成事件校验、实体解析和权限检查。

## 5. 端到端流程

```text
HTTP请求或operation.requested事件
→ 校验Schema、来源、有效期和event_id
→ 识别固定意图并提取参数
→ 将名称解析为客户、产品、账户等唯一ID
→ 创建MySQL操作草稿及参数版本
→ 校验操作者角色和客户数据范围
→ 校验基本业务条件
→ 发布risk.check.requested
→ 状态变为WAITING_RISK_REVIEW
→ 等待risk.check.completed
```

风控结果：

```text
approved
→ 进入确认流程

approved_with_warning
→ 保存并展示警告
→ 进入确认流程

rejected
→ 状态变为RISK_REJECTED
→ 发布结果给来源Agent

manual_review
→ 状态变为MANUAL_REVIEW
→ 等待控制事件
```

风控通过并确认后：

```text
复核操作版本、参数哈希、确认有效期和权限
→ 获取幂等锁
→ 调用固定Mock Tool
→ MySQL事务保存执行结果和审计
→ 发布operation.succeeded或operation.failed
→ 发布transaction.created给风控Agent
```

## 6. 状态机

正常路径：

```text
DRAFT
→ RESOLVING_ENTITIES
→ VALIDATING
→ WAITING_RISK_REVIEW
→ RISK_APPROVED
→ PENDING_CONFIRMATION
→ CONFIRMED
→ EXECUTING
→ SUCCEEDED
```

异常和等待状态：

```text
NEED_MORE_INFORMATION
PERMISSION_DENIED
VALIDATION_FAILED
RISK_REJECTED
RISK_REVIEW_TIMEOUT
MANUAL_REVIEW
CANCELLED
EXPIRED
FAILED
PENDING_VERIFICATION
```

所有状态变化必须经过状态机并写入审计。参数发生变化时生成新版本，使旧风控结果和旧确认失效，并重新发起风控。

## 7. Redis事件协议

所有事件至少包含：

```json
{
  "event_id": "EVT001",
  "event_type": "operation.requested",
  "source_agent": "advisor",
  "target_agents": ["operator"],
  "correlation_id": "OP001",
  "operation_id": "OP001",
  "task_id": "T001",
  "session_id": "S001",
  "customer_id": "C001",
  "payload": {},
  "occurred_at": "2026-07-23T10:00:00+08:00",
  "expires_at": "2026-07-23T10:05:00+08:00",
  "schema_version": "1.0"
}
```

业务操作 Agent 发布：

```text
agent:risk:command
agent:result
event:transaction
```

主要事件类型：

```text
risk.check.requested
operation.created
operation.need_more_information
operation.pending_confirmation
operation.confirmed
operation.succeeded
operation.failed
operation.cancelled
operation.manual_review_required
transaction.created
```

最终操作结果必须发给原始 `source_agent`，交易结果同时发给风控 Agent。

Redis Pub/Sub 不提供离线重放，因此 MySQL 保存等待风控状态、请求事件、截止时间和结果事件。风控超时不得默认通过，可有限重发，最终进入超时或人工处理。

## 8. MySQL数据模型

### operations

保存操作主记录、来源、身份、意图、当前状态、版本、风控状态、确认要求、幂等键、结果和错误。

### operation_versions

保存每一版 `params_json`、`params_hash`、修改人和创建时间。

### risk_reviews

保存操作版本、请求事件、结果事件、决定、风险级别、规则命中、警告、原因和有效期。

### operation_confirmations

保存操作版本、参数哈希、确认人、确认方式、状态和有效期。

### execution_attempts

保存每次 Tool 调用的请求、响应、状态、幂等键和时间。

### operation_audit_logs

保存操作的不可变状态轨迹、执行人、详情和 `trace_id`。

### processed_events

保存已处理 Redis 事件；`event_id` 建立唯一索引以防重复消费。

## 9. 权限和风控边界

业务操作 Agent 负责：

- 事件来源和结构；
- 操作者角色；
- 操作者对客户、账户和字段的数据权限；
- 参数完整性；
- 实体唯一性；
- 基本业务状态；
- 用户确认；
- 幂等和审计。

风控 Agent 负责：

- 风险适当性；
- 风险规则；
- 可疑交易；
- 风险级别；
- 通过、警告、拒绝或人工审核。

业务操作 Agent 只消费并执行风控结论，不自行修改或重算结论。

## 10. Mock API

实现以下Mock接口：

```text
POST  /mock/operations/purchase
POST  /mock/operations/redeem
POST  /mock/operations/transfer
POST  /mock/operations/risk-assessment
PATCH /mock/customers/{customer_id}
GET   /mock/products/{product_id}
POST  /mock/suspicious-reports
POST  /mock/workorders
GET   /mock/operations/{operation_id}/status
```

Mock API 必须支持成功、参数错误、余额或份额不足、账户冻结、产品停售、重复请求、超时和状态未知。金额使用 `Decimal`，API 中以字符串传输。

## 11. 错误处理

统一错误码：

```text
OP_INTENT_UNKNOWN
OP_PARAM_MISSING
OP_PARAM_INVALID
OP_EVENT_INVALID
OP_EVENT_DUPLICATE
OP_EVENT_EXPIRED
OP_SOURCE_UNTRUSTED
OP_ENTITY_NOT_FOUND
OP_ENTITY_AMBIGUOUS
OP_PERMISSION_DENIED
OP_CUSTOMER_OUT_OF_SCOPE
OP_RISK_REVIEW_TIMEOUT
OP_RISK_REJECTED
OP_RISK_RESULT_INVALID
OP_CONFIRMATION_REQUIRED
OP_CONFIRMATION_EXPIRED
OP_CONFIRMATION_VERSION_MISMATCH
OP_DUPLICATE_REQUEST
OP_MOCK_API_FAILED
OP_MOCK_API_TIMEOUT
OP_STATUS_UNKNOWN
OP_MANUAL_REVIEW_REQUIRED
```

Mock API响应超时不直接判定失败，进入 `PENDING_VERIFICATION` 并按 `operation_id` 查询结果。涉及资金和状态变化的请求不得盲目重试。

## 12. 安全与可靠性

- JWT 或可信事件身份提供操作者信息，不信任正文中伪造的角色；
- 其他 Agent 的事件必须通过来源白名单和 Schema 校验；
- 风控结果必须匹配 `operation_id`、操作版本、来源和有效期；
- 关键参数变化后重新风控和确认；
- `event_id` 和 `idempotency_key` 建立唯一约束；
- 高风险操作未确认不得执行；
- 日志脱敏，不记录密码、完整验证码或密钥；
- 审计写入失败时，不继续自动执行高风险操作。

## 13. 测试

### 单元测试

- 八类意图与参数 Schema；
- 权限矩阵；
- 状态机；
- 参数版本与哈希；
- 事件去重；
- 风控结果关联；
- 确认有效期；
- 幂等；
- 错误码。

### Redis集成测试

- 接收其他 Agent 请求；
- 发布风控请求；
- 接收通过、警告、拒绝和人工审核；
- 拒绝错误来源、过期和不匹配结果；
- 处理重复结果；
- 风控超时；
- 将执行结果返回来源 Agent；
- 将交易结果发送风控 Agent。

### MySQL集成测试

- 操作草稿、参数版本、风控审核、确认、执行尝试和审计；
- 状态并发更新；
- `event_id` 和幂等键唯一约束。

### 端到端测试

```text
投顾发布申购请求
→ Operator接收
→ 发布风控请求
→ 模拟风控通过
→ 用户确认
→ Mock API执行
→ MySQL保存
→ 发布结果给投顾和风控
```

同时覆盖风控拒绝、风控超时、参数改变、取消、重复事件、未授权操作、API超时和恶意事件。

## 14. 验收标准

```text
未收到风控通过而执行次数 = 0
风控拒绝后执行次数 = 0
旧版本风控结果被复用次数 = 0
未经确认的高风险操作执行次数 = 0
重复操作次数 = 0
来源Agent未收到最终结果次数 = 0
交易结果未通知风控次数 = 0
跨客户数据串扰次数 = 0
审计记录完整率 = 100%
```

## 15. 非目标

本次不实现客服、投顾、风控或数据分析 Agent 的业务代码；仅实现与它们通信所需的事件协议、业务操作 Agent 的订阅和发布代码，以及测试用事件模拟器。

