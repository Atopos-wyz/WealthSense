# 业务操作 Agent

## 启动

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

如果 `.env` 中未同时提供 MySQL 和 Redis 地址，应用自动使用内存 Repository 和事件发布器，便于本地演示。

## HTTP入口

```text
POST /api/operation/chat
POST /api/operation/{operation_id}/confirm
POST /api/operation/{operation_id}/cancel
GET  /api/operation/{operation_id}?request_id=...
```

操作者身份通过请求头提供：

```text
X-Operator-Id
X-Operator-Role
X-Organization-Id
```

## Redis订阅

```text
agent:operator:command
agent:operator:risk_result
agent:operator:control
```

其他 Agent 发起操作时发布 `operation.requested`。业务操作 Agent 创建操作后发布 `risk.check.requested` 到 `agent:risk:command`，只有收到风控 Agent 发布的有效 `risk.check.completed` 后才会进入确认或执行。

## Redis发布

```text
agent:risk:command
agent:result
event:transaction
```

操作最终结果发送给原始来源 Agent；资金和持仓操作成功后同时发布 `transaction.created` 给风控 Agent。

## 运行测试

```powershell
python -m unittest discover -s tests -v
```

