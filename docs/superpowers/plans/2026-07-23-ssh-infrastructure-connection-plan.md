# SSH 基础设施连接实施计划

## 任务 1：配置模型

- 在 `Settings` 中增加 SSH 开关、服务器、认证、known_hosts 和远端端口配置。
- SSH 密码使用 `SecretStr`。
- 启用 SSH 时校验必填字段。
- 更新 `.env.example`，只保留占位符。

## 任务 2：SSH 隧道组件

- 新建 `app/config/ssh_tunnel.py`。
- 使用 Paramiko 和本机 `known_hosts` 校验服务器身份。
- 一个 SSH Transport 承载 MySQL、Redis 两个 `direct-tcpip` 转发。
- 本地监听端口由操作系统动态分配。
- 实现幂等关闭、keepalive 和不含密码的错误。
- 实现 MySQL/Redis URL 端点重写。

## 任务 3：容器生命周期

- `build_container()` 在创建数据库和 Redis 客户端前启动隧道。
- 使用重写后的 URL 创建 SQLAlchemy Engine 与 Redis Client。
- 启动阶段执行 MySQL 建表和 Redis PING。
- 任一步失败时释放 Redis、Engine 和 SSH 隧道。
- `AppContainer.close()` 最后关闭隧道。

## 任务 4：依赖与测试

- 在 `requirements.txt` 增加 Paramiko。
- 增加配置校验、URL 重写、隧道生命周期和容器回滚测试。
- 运行现有全部测试，确保内存模式和直连模式不回归。

## 任务 5：真实环境配置

- 创建 Git 忽略的 `.env`。
- 配置服务器内网 MySQL `finance` 和 Redis DB 0。
- 配置 SSH 服务器与本机 known_hosts。
- 不提交或输出真实密码。

## 任务 6：真实环境验收

- 启动应用自己的 SSH 隧道。
- 验证 MySQL 版本、当前数据库和业务表。
- 验证 Redis PING。
- 验证 `/ready` 返回 `mysql_redis`。
- 发布测试事件并验证 Redis Stream。
- 关闭应用并确认连接资源释放。

