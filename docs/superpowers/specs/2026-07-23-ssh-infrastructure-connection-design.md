# WealthSense SSH 基础设施连接设计

## 目标

让业务操作 Agent 在不依赖 DBeaver 或 Redis Insight 运行的情况下，自行通过 SSH 隧道连接服务器内部的 MySQL 和 Redis。DBeaver、Redis Insight 与 WealthSense 最终访问同一套服务器数据。

本次只增加基础设施连接能力，不修改八类业务意图、风控事件协议、操作状态机或 Mock API 行为。

## 连接架构

```text
WealthSense FastAPI
        |
        | SSH（校验 known_hosts）
        v
114.132.213.216:22
        |
        +-- 127.0.0.1:3306 --> MySQL / finance
        |
        +-- 127.0.0.1:6379 --> Redis / DB 0
```

应用启动时创建一个 SSH 客户端会话，并在该会话上建立两个独立的本地 TCP 转发端口。MySQL 和 Redis 客户端只连接自动分配的本地端口，服务器的 3306 和 6379 不需要暴露到公网。

本地端口使用操作系统分配的空闲端口，避免与本机 MySQL、Redis、DBeaver 隧道或 Redis Insight 冲突。

## 配置

在现有 `Settings` 中增加以下配置：

```text
WEALTHSENSE_SSH_TUNNEL_ENABLED
WEALTHSENSE_SSH_HOST
WEALTHSENSE_SSH_PORT
WEALTHSENSE_SSH_USERNAME
WEALTHSENSE_SSH_PASSWORD
WEALTHSENSE_SSH_KNOWN_HOSTS
WEALTHSENSE_SSH_REMOTE_MYSQL_HOST
WEALTHSENSE_SSH_REMOTE_MYSQL_PORT
WEALTHSENSE_SSH_REMOTE_REDIS_HOST
WEALTHSENSE_SSH_REMOTE_REDIS_PORT
```

现有 `WEALTHSENSE_MYSQL_URL` 和 `WEALTHSENSE_REDIS_URL` 继续描述服务器内部目标：

```text
mysql+aiomysql://<user>:<password>@127.0.0.1:3306/finance
redis://default:<password>@127.0.0.1:6379/0
```

隧道启动后，程序只在内存中把 URL 的主机和端口替换为本地转发地址。密码使用 `SecretStr` 保存，日志、异常信息和配置对象输出不得显示明文。

真实凭据写入项目根目录 `.env`；该文件已经被 Git 忽略。`.env.example` 只保留占位值。

## 组件边界

新增 `app/config/ssh_tunnel.py`：

- `SshTunnelManager`：建立 SSH 连接、启动 MySQL/Redis 转发、提供本地端口、关闭资源。
- `TunnelEndpoint`：描述一个已经建立的本地转发端点。
- TCP 转发处理器：把本地连接映射为 Paramiko `direct-tcpip` channel。
- URL 重写函数：保持用户名、密码、数据库和查询参数不变，只替换主机与端口。

`Settings` 只负责读取和校验配置，不建立网络连接。

`build_container()` 负责组合生命周期：

1. 校验 MySQL、Redis 与 SSH 配置完整性。
2. 启动 SSH 隧道。
3. 使用隧道端点创建 SQLAlchemy Engine 和 Redis Client。
4. 创建 MySQL 表。
5. 启动现有 Redis 发布、订阅、Stream 和状态存储能力。
6. 任一步失败时，按相反顺序关闭已经创建的资源。

`AppContainer.close()` 的关闭顺序为：

1. 停止 Redis 订阅；
2. 关闭 Redis Client；
3. 释放 SQLAlchemy Engine；
4. 关闭本地转发服务；
5. 关闭 SSH 会话。

## 安全要求

- 使用本机 `known_hosts` 验证服务器指纹，未知或变化的主机密钥必须拒绝连接。
- 不使用 `AutoAddPolicy`。
- SSH、MySQL、Redis 密码不写入代码、Git、测试快照或日志。
- SSH 传输开启 keepalive，及时发现失效连接。
- MySQL 和 Redis 仍只访问服务器的 `127.0.0.1`。
- `/ready` 同时检查 MySQL `SELECT 1` 和 Redis `PING`；任何一项失败均返回 503。
- DBeaver 和 Redis Insight 不参与应用运行，也不会被应用修改。

## 失败处理

- SSH 认证失败、主机指纹不匹配、远端端口不可达：应用拒绝启动并返回不含密码的明确错误。
- MySQL 建表失败：关闭 Engine、Redis（如已创建）和 SSH 隧道。
- Redis 认证或连接失败：关闭 Redis、Engine 和 SSH 隧道。
- 运行期间隧道中断：依赖调用失败，`/ready` 返回 503；不自动降级到内存模式，避免把生产数据写入错误位置。
- 正常退出或启动取消：幂等关闭全部连接和转发线程。

## 可观测结果

应用成功启动后：

- DBeaver 刷新 `finance` 数据库可以看到业务操作 Agent 创建的表和数据。
- Redis Insight 的 DB 0 可以看到操作状态 Key、幂等 Key 和 Redis Stream。
- Pub/Sub 是瞬时消息，只有实时订阅对应频道时可见。
- Redis Stream `agent:events:durable` 可以事后查看。

## 测试与验收

### 单元测试

- SSH 配置完整性校验。
- MySQL URL 和 Redis URL 主机端口重写。
- 隧道启动、重复关闭和异常回滚。
- 未知主机密钥被拒绝。
- 未启用 SSH 时保持现有直连与内存适配器行为。

### 真实环境验收

1. 通过应用自己的 SSH 隧道连接服务器。
2. MySQL `SELECT 1` 成功，服务器版本和当前数据库可读取。
3. Redis `PING` 成功。
4. 应用自动创建业务操作 Agent 所需表。
5. `/ready` 返回 `{"status":"ready","mode":"mysql_redis"}`。
6. 发布一条测试事件，Redis Stream 和目标 Pub/Sub 频道写入成功。
7. DBeaver 和 Redis Insight 能查看同一份数据。
8. 关闭应用后，本地转发端口和 SSH 连接被释放。

