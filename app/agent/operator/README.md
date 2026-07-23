# 业务操作 Agent

## 启动

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

开发环境未提供 MySQL 和 Redis 地址时，应用使用内存适配器；只配置其中一个会拒绝启动。生产环境必须同时配置 MySQL、Redis、JWT 密钥和五个 Agent 各自的事件签名密钥。

## HTTP入口

```text
POST /api/operation/chat
POST /api/operation/{operation_id}/confirm
POST /api/operation/{operation_id}/cancel
GET  /api/operation/{operation_id}?request_id=...
```

操作者身份通过 JWT 提供，不能由客户端任意填写角色或客户范围：

```text
Authorization: Bearer <token>
```

Token 至少包含 `sub`、`role`、`organization_id`、`customer_ids`、`account_ids`、`holding_ids`、`iss` 和 `exp`。这些范围由统一身份/授权服务签发，业务操作 Agent 不使用客户端自报角色，也不维护硬编码账户归属。HTTP 查询、修改、确认、取消和状态核查接口都会再次检查组织、角色、客户、账户及持仓范围。

## Redis订阅

```text
agent:operator:command
agent:operator:risk_result
agent:operator:control
```

其他 Agent 发起操作时发布 `operation.requested`，并携带用户授权 JWT。Redis 事件采用每个 Agent 独立的 HMAC 密钥签名，事件类型必须发布到指定频道。业务操作 Agent 创建操作后发布 `risk.check.requested` 到 `agent:risk:command`，只有收到风控 Agent 发布的有效 `risk.check.completed` 后才会进入确认或执行。

风控结果必须同时匹配 `operation_id`、`operation_version`、`request_event_id` 和有效期。`manual_review` 会进入人工复核状态，之后由 `risk.manual_review.completed` 明确结束。

## Redis发布

```text
agent:risk:command
agent:result
event:transaction
```

操作最终结果发送给原始来源 Agent；资金和持仓操作成功后同时发布 `transaction.created` 给风控 Agent。

## 工程安全

- 固定八类意图与各自 Pydantic 参数模型。
- 所有操作先发给风控 Agent，业务操作 Agent 不自行做风控结论。
- 大额申购、转账及敏感变更使用参数版本、参数哈希和限时二次确认。
- `(source_agent, operator_id, organization_id, request_id)` 唯一，操作执行另有幂等锁，既防止重复请求，也避免不同登录主体的请求号互相命中。
- 数据库状态更新同时比较状态、操作版本和当前风控请求 ID；重复确认、并发风控结果或旧版本回执只有一个能够成功。
- Mock API 超时进入 `pending_verification`，后台自动核查最终结果，不盲目重试。
- 风控等待、确认等待都有过期扫描；人工审核有完成事件。
- 关键步骤写入操作版本、风控审核、确认、执行尝试和审计记录。
- 状态、审计和对应 `operation.<status>` Outbox 在同一数据库事务提交；成功交易的 `transaction.created` 也随 `SUCCEEDED` 原子入 Outbox。风控请求、风控审核记录和对应 Outbox 同样原子提交。

事件交付语义为“至少一次”：所有消费方必须用 `event_id` 去重。每个出站事件先进入 MySQL Outbox，再同时写入 Redis Stream `agent:events:durable` 和对应 Pub/Sub 频道。Pub/Sub 用于实时通知，Stream 用于消费者离线恢复；其他 Agent 需要建立各自的 Consumer Group。

如果数据库已运行过早期版本，请先备份，再执行
`app/dao/mysql/migrations/001_operator_hardening.sql`。全新数据库不需要手动执行，启动时会创建最终表结构。

## 运行测试

```powershell
python -m unittest discover -s tests -v
```
