# WealthSense 数据库 Mock 实施计划

设计依据：`docs/superpowers/specs/2026-07-23-database-mock-design.md`

## 任务 1：定义 Operator 专属数据库实体

- 新建 `app/models/entities/mock_business.py`。
- 定义九张 `operator_mock_*` 表及唯一约束、索引、金额精度和时间字段。
- 在 `app/models/entities/__init__.py` 显式导出实体，使现有 `Base.metadata.create_all()` 只创建缺失的 Operator Mock 表。
- 不映射、不迁移、不修改任何共享表。
- 增加元数据测试，验证所有新表均以 `operator_mock_` 开头。

## 任务 2：建立数据库 Mock Repository

- 新建 `app/dao/mysql/mock_business_repository.py`。
- 定义 `MockBusinessRepository` 协议。
- 实现 `SqlAlchemyMockBusinessRepository`：
  - 只读解析 `sys_user`、`fin_product`、`fin_holdings`；
  - 查询和锁定 Mock 账户；
  - 计算共享初始持仓加 Mock 增量；
  - 写入交易、持仓增量、资料更新、测评、上报和工单；
  - 查询和保存幂等执行结果。
- 共享表查询使用固定 SQL 和绑定参数，不拼接用户输入。
- 产品查询字段使用代码白名单，不把请求字段直接拼入 SQL。

## 任务 3：实现八类数据库 Handler

- 新建 `app/tool/operation/database_registry.py`。
- 实现：
  - 申购 Handler；
  - 赎回 Handler；
  - 转账 Handler；
  - 风险测评重做 Handler；
  - 客户信息更新 Handler；
  - 产品查询 Handler；
  - 可疑交易上报 Handler；
  - 工单创建 Handler。
- 每个 Handler 接收已校验参数并返回稳定字典。
- 申购、赎回、转账使用 `Decimal` 和数据库事务。
- 业务失败回滚全部变化，并保存稳定失败结果。
- 新申购持仓返回 `MH_*` 编号，支持后续赎回。

## 任务 4：保留兼容的 Registry 契约

- 在 `app/tool/operation/registry.py` 定义 Registry 协议。
- 保留现有 `OperationToolRegistry` 作为内存版兼容入口。
- 新增数据库版 Registry，保持 `execute()` 与 `get_status()` 签名不变。
- 保持现有 Mock 错误类型和 API 状态码映射。
- 支持 `simulate_failure`、`simulate_timeout` 和超时后状态查询。

## 任务 5：接入应用容器

- 修改 `app/container.py`。
- 外部 MySQL/Redis 模式注入 `SqlAlchemyMockBusinessRepository` 和数据库版 Registry。
- 内存模式继续注入现有内存 Registry。
- 不改变 `OperationService`、Business Operator Agent 或 Redis 事件协议。
- 增加容器选择测试。

## 任务 6：实现安全初始化命令

- 新建 `app/scripts/seed_mock_business.py` 及包初始化文件。
- 通过现有 SSH 隧道和配置连接服务器。
- 只读选择现有客户和在售产品。
- 只向 `operator_mock_accounts` 与 `operator_mock_product_details` 执行幂等补充。
- 不覆盖已有余额、产品详情和操作历史。
- 不提供清空或删除服务器数据的命令。

## 任务 7：完善测试

- 新增数据库实体与 Registry 单元测试。
- 覆盖八类意图。
- 覆盖余额不足、份额不足、冻结账户、产品停售、币种不匹配和目标不存在。
- 覆盖事务回滚和幂等结果复用。
- 覆盖首次申购生成 Mock 持仓编号及随后赎回。
- 覆盖已提交但响应超时后的 `get_status()`。
- 运行现有全部测试，确保风控、确认、Redis 和恢复流程不回归。

## 任务 8：服务器建表与初始化

- 使用应用现有 SSH 隧道连接服务器 `finance`。
- 记录执行前共享表结构摘要。
- 执行 `Base.metadata.create_all()`，只创建缺失的 `operator_mock_*` 表。
- 执行安全初始化命令。
- 验证 DBeaver 可见新表和初始化记录。
- 对比执行前后共享表结构，确认没有变化。

## 任务 9：端到端验收

- 使用隔离的测试组织和操作编号执行申购、赎回、转账。
- 验证余额和持仓增量。
- 重复相同幂等键，验证没有第二笔交易。
- 模拟超时并对账。
- 执行资料更新，确认 `sys_user` 未变化。
- 执行风险测评、产品查询、可疑上报和工单创建。
- 验证现有 Redis 风控请求和结果事件仍可工作。
- 运行 `pip check`、全部测试和 `/ready` 健康检查。

## 任务 10：提交与交付

- 检查 Git 差异，不提交 `.env`、密码或运行时数据。
- 检查中文编码和用户可见错误消息。
- 提交数据库 Mock 实现。
- 提供新表、初始化命令、测试结果和跨 Agent 联调入口说明。
