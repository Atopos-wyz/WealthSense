# WealthSense 业务操作 Agent 数据库 Mock 设计

日期：2026-07-23  
状态：已完成对话评审  
范围：将业务操作 Agent 的内存 Mock 升级为服务器 MySQL 持久化 Mock

## 1. 目标

将现有 `OperationToolRegistry` 的进程内存结果升级为数据库持久化实现，使八类业务操作在服务重启后仍可查询，并能在 DBeaver 中看到模拟余额、持仓、交易、测评、资料变更、可疑上报和工单。

本次升级保持以下接口不变：

- 业务操作 Agent 的输入输出 Schema；
- `OperationService` 的风控、确认、状态机和幂等流程；
- Redis 跨 Agent 事件协议；
- `/mock/operations/{intent}` 与 `/mock/operations/{operation_id}/status`；
- `OperationToolRegistry.execute()` 与 `get_status()` 的调用契约。

## 2. 数据安全边界

服务器 `finance` 数据库已有以下共享表：

- `sys_user`
- `fin_customer_profile`
- `fin_product`
- `fin_holdings`
- `fin_risk_assessment`
- `fin_profile_evaluation`
- `fin_profile_field_audit`
- `fin_suitability_check`

这些共享表只读使用。本功能不对共享表执行 `ALTER`、`DROP`、`TRUNCATE`、`UPDATE`、`INSERT` 或 `DELETE`，也不为共享表添加外键。

本功能只创建和写入 `operator_mock_*` 表。建表仅使用 `CREATE TABLE IF NOT EXISTS`，避免影响其他成员的表结构和数据。

## 3. 架构

采用现有 MVC + Agent + Service + Tool + Repository 结构：

```text
HTTP / Redis 请求
→ BusinessOperatorAgent
→ OperationService
→ OperationToolRegistry
→ MockBusinessRepository
→ 服务器 MySQL
→ OperationService 发布 Redis 结果事件
```

组件职责：

- `InMemoryOperationToolRegistry`：保留现有内存行为，用于快速单元测试；
- `DatabaseOperationToolRegistry`：负责数据库版意图路由、事务和幂等；
- `MockBusinessRepository`：定义数据库 Mock 访问协议；
- `SqlAlchemyMockBusinessRepository`：实现 MySQL 查询、锁定和写入；
- 八类 Handler：分别实现一种业务操作，不处理 HTTP 或 Redis；
- `OperationService`：继续负责风控等待、确认、状态机、审计和跨 Agent 事件。

连接外部 MySQL/Redis 时，容器注入数据库版 Registry；无外部基础设施的测试环境注入内存版 Registry。

## 4. 共享数据对齐

共享数据只读映射如下：

| 共享表 | 用途 |
|---|---|
| `sys_user` | 客户身份、手机号、邮箱和状态 |
| `fin_customer_profile` | 客户画像与当前风险等级 |
| `fin_product` | 产品代码、名称、类型、风险等级和状态 |
| `fin_holdings` | 模拟前的初始持仓 |
| `fin_risk_assessment` | 已有风险测评记录 |
| `fin_profile_evaluation` | 已有画像评估结果 |

逻辑标识解析：

- 客户外部 ID 可使用 `sys_user.user_no` 或数字主键；
- 产品外部 ID 可使用 `fin_product.product_code` 或数字主键；
- 持仓外部 ID 可使用 `H{fin_holdings.id}` 或数字主键；
- Mock 账户使用独立账户编号并逻辑关联 `sys_user.id`。

Repository 负责把 Agent 外部 ID 解析为服务器内部主键。共享表不增加外键或索引。

## 5. Operator 专属数据表

### 5.1 `operator_mock_accounts`

保存模拟账户：

- `id`
- `account_no`
- `organization_id`
- `customer_id`
- `currency`
- `available_balance`
- `status`
- `created_at`
- `updated_at`

唯一约束：`account_no`。

### 5.2 `operator_mock_holding_changes`

保存相对 `fin_holdings` 初始持仓的增量账本：

- `id`
- `change_id`
- `operation_id`
- `organization_id`
- `customer_id`
- `account_no`
- `product_id`
- `holding_no`
- `base_holding_id`
- `change_type`
- `shares_delta`
- `amount`
- `created_at`

`holding_no` 是业务操作 Agent 对外使用的稳定持仓编号。已有共享持仓映射为
`H{fin_holdings.id}`；首次申购没有共享持仓的产品时生成新的 `MH_*` 编号。
当前模拟份额通过“共享初始份额 + 同一 `holding_no` 的 Mock 增量合计”计算。
清仓后保留增量账本，不删除共享持仓。

### 5.3 `operator_mock_transactions`

保存申购、赎回和转账流水：

- `id`
- `transaction_no`
- `operation_id`
- `organization_id`
- `customer_id`
- `transaction_type`
- `from_account_no`
- `to_account_no`
- `product_id`
- `amount`
- `shares`
- `currency`
- `status`
- `created_at`
- `completed_at`

唯一约束：`transaction_no`、`operation_id`。

### 5.4 `operator_mock_product_details`

补充 `fin_product` 没有的模拟字段：

- `id`
- `product_id`
- `net_value`
- `minimum_purchase_amount`
- `currency`
- `redeemable`
- `updated_at`

唯一约束：`product_id`。

### 5.5 `operator_mock_profile_updates`

保存手机号、邮箱和地址的模拟变更，不覆盖 `sys_user`：

- `id`
- `update_no`
- `operation_id`
- `organization_id`
- `customer_id`
- `field_name`
- `old_value`
- `new_value`
- `created_at`

查询有效资料时优先读取最新 Mock 更新，没有增量时回退共享表。

### 5.6 `operator_mock_risk_assessments`

保存模拟重做风险测评：

- `id`
- `assessment_no`
- `operation_id`
- `organization_id`
- `customer_id`
- `questionnaire_version`
- `answers_json`
- `status`
- `risk_level`
- `total_score`
- `valid_until`
- `created_at`

不写入 `fin_risk_assessment`。

### 5.7 `operator_mock_suspicious_reports`

保存可疑交易上报：

- `id`
- `report_no`
- `operation_id`
- `organization_id`
- `customer_id`
- `transaction_no`
- `reason`
- `evidence_refs_json`
- `status`
- `created_at`

### 5.8 `operator_mock_work_orders`

保存模拟工单：

- `id`
- `work_order_no`
- `operation_id`
- `organization_id`
- `customer_id`
- `work_order_type`
- `description`
- `priority`
- `status`
- `created_at`
- `updated_at`

### 5.9 `operator_mock_api_executions`

保存 Mock API 执行和幂等结果：

- `id`
- `operation_id`
- `idempotency_key`
- `intent`
- `request_json`
- `response_json`
- `error_code`
- `status`
- `started_at`
- `completed_at`

唯一约束：`operation_id`、`idempotency_key`。

## 6. 八类操作语义

### 6.1 申购

1. 解析客户、账户和产品；
2. 锁定 Mock 账户；
3. 检查账户状态、币种、余额、产品状态和起购金额；
4. 扣减 Mock 账户余额；
5. 复用已有持仓编号，或为首次持有的产品生成 `MH_*` 持仓编号；
6. 写入正向持仓增量；
7. 写入申购交易；
8. 保存幂等成功结果，并在响应中返回持仓编号。

上述变化在一个 MySQL 事务中提交。

### 6.2 赎回

1. 解析共享基础持仓或 Mock 持仓；
2. 计算共享初始份额与 Mock 增量之和；
3. 锁定相关 Mock 账户和持仓增量；
4. 检查可赎回份额；
5. 写入负向持仓增量；
6. 按 Mock 净值增加账户余额；
7. 写入赎回交易和幂等结果。

### 6.3 转账

1. 按账户编号排序后锁定转出和转入账户；
2. 检查状态、币种和余额；
3. 转出账户扣减，转入账户增加；
4. 写入转账流水和幂等结果。

固定锁顺序用于降低死锁概率。

### 6.4 风险测评重做

保存答案、问卷版本和提交状态，返回测评编号。业务操作 Agent 不计算风险等级；
`risk_level`、`total_score` 和有效期允许为空，后续可由正式测评服务回填。
结果只写 `operator_mock_risk_assessments`，不写共享测评表。

### 6.5 客户信息更新

只允许 `phone`、`email`、`address`。保存旧值和新值到 `operator_mock_profile_updates`，不修改 `sys_user`。

### 6.6 产品查询

读取 `fin_product` 并左连接 `operator_mock_product_details`。请求字段必须经过白名单过滤。

### 6.7 可疑交易上报

校验目标交易存在于 `operator_mock_transactions` 后，写入
`operator_mock_suspicious_reports`。如果将来出现统一共享交易表，再通过
Repository 适配器扩展查询来源。

### 6.8 工单创建

校验客户存在后写入 `operator_mock_work_orders`，返回唯一工单号。

## 7. 幂等与超时

收到 `operation_id` 和 `idempotency_key` 后：

1. 查询 `operator_mock_api_executions`；
2. 已成功则返回原响应；
3. 已失败则返回原错误；
4. 正在执行则返回当前状态，不重复执行业务变化；
5. 首次调用创建执行记录并开始事务。

成功路径中，业务数据变化与成功执行结果在同一事务提交。业务校验失败时先回滚
所有业务变化，再用独立短事务保存失败执行结果，使同一幂等键重复请求时返回原错误。

`simulate_timeout` 支持“数据库事务已提交，但调用方收到超时”。此时 `get_status(operation_id)` 必须返回数据库中的真实成功结果，供现有 `pending_verification` 对账流程使用。

资金、份额和状态变化在结果未知时不得盲目重试。

## 8. 错误处理

统一业务错误：

- `OP_CUSTOMER_NOT_FOUND`
- `OP_ACCOUNT_NOT_FOUND`
- `OP_PRODUCT_NOT_FOUND`
- `OP_HOLDING_NOT_FOUND`
- `OP_ACCOUNT_FROZEN`
- `OP_INSUFFICIENT_BALANCE`
- `OP_INSUFFICIENT_SHARES`
- `OP_PRODUCT_INACTIVE`
- `OP_MIN_PURCHASE_NOT_MET`
- `OP_CURRENCY_MISMATCH`
- `OP_TRANSACTION_NOT_FOUND`
- `OP_DUPLICATE_REQUEST`
- `OP_MOCK_API_TIMEOUT`
- `OP_MOCK_API_FAILED`

数据库约束、死锁和连接异常转换为稳定错误，不向 Agent 暴露 SQL、连接地址或凭据。可安全重试的临时数据库错误使用有限次数重试；结果未知的资金操作进入 `pending_verification`。

## 9. 初始化数据

提供独立、可重复执行的初始化命令：

1. 只读选择现有客户和在售产品标识；
2. 只向 `operator_mock_accounts` 和 `operator_mock_product_details` 补充演示记录；
3. 已存在记录保持不变；
4. 不清空交易、持仓增量、工单或其他历史；
5. 不提供自动清空服务器数据的入口。

初始化失败不会影响应用启动；未初始化的业务操作返回明确的账户或产品详情缺失错误。

## 10. Redis 与风控边界

数据库 Mock 不执行风险适当性判断。流程保持为：

```text
业务操作请求
→ OperationService 发布 risk.check.requested
→ 风控 Agent 返回 risk.check.completed
→ 必要时用户确认
→ DatabaseOperationToolRegistry 执行数据库 Mock
→ OperationService 发布 operation.succeeded / operation.failed
→ 交易类操作继续发布 transaction.created
```

其他 Agent 不需要修改事件 Schema、频道或调用代码。

## 11. 测试

### 11.1 单元测试

- 八类 Handler；
- 金额、份额和净值精度；
- 字段白名单；
- 错误码；
- ID 解析；
- 幂等结果复用。

### 11.2 Repository 测试

- 事务提交与回滚；
- 账户行锁和固定锁顺序；
- 共享初始持仓与 Mock 增量合并；
- 唯一约束；
- 超时后的状态查询；
- 共享表只读约束。

### 11.3 回归测试

现有业务操作、风控、Redis 事件、确认、幂等和恢复测试必须全部通过。

### 11.4 服务器冒烟测试

通过现有 SSH 隧道连接服务器 MySQL，仅写 `operator_mock_*` 表：

- 申购后余额减少、模拟持仓增加；
- 赎回后模拟份额减少、余额增加；
- 转账一减一增；
- 重复请求不产生第二笔交易；
- 超时后能查询真实结果；
- 信息更新不改变 `sys_user`；
- 共享表的结构和数据不发生变化。

测试记录使用独立 `organization_id` 和操作编号，避免与演示数据混淆。

## 12. 验收标准

- DBeaver 可以查看全部数据库 Mock 记录；
- 服务重启后 Mock 结果仍然存在；
- 八类意图均由数据库实现；
- 申购、赎回和转账具备原子性；
- 重复请求不会重复扣款、增加持仓或创建工单；
- 超时后的真实结果可查询；
- Redis 风控和跨 Agent 事件协议不变；
- 共享表没有结构变化，也没有被模拟操作直接写入；
- 现有测试和新增数据库 Mock 测试全部通过。

## 13. 非目标

- 不实现真实金融交易；
- 不修改客服、投顾、风控或数据分析 Agent；
- 不替代风控 Agent 的判断；
- 不修改共享业务表结构和数据；
- 不拆分独立 Mock 微服务；
- 不提供服务器 Mock 数据一键清空功能。
