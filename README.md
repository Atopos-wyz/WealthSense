# WealthSense

WealthSense 是一个面向智能金融服务场景的财富管理系统。项目计划基于 Python、FastAPI 以及 MySQL、Redis、Milvus、Neo4j、MinIO 构建，覆盖 RAG、GraphRAG、NL2SQL、NL2API、客户画像、风控监测和多 Agent 协作等能力。

## 项目目录

```text
WealthSense/
├── app/                         # 应用程序主体
│   ├── agent/                   # AI Agent 编排层
│   │   ├── core/                # Agent 公共骨架、路由及基础能力
│   │   ├── customer/            # 智能客服 Agent
│   │   ├── advisor/             # 投顾助手 Agent
│   │   ├── risk/                # 风控监测 Agent
│   │   ├── analyst/             # 数据分析 Agent
│   │   └── operator/            # 业务操作 Agent
│   ├── api/                     # FastAPI 路由层，承担 MVC 的 Controller 职责
│   │   ├── chat/                # 统一对话及各 Agent 对话接口
│   │   ├── knowledge/           # 知识库管理接口
│   │   ├── profile/             # 客户画像接口
│   │   ├── product/             # 金融产品查询与推荐接口
│   │   ├── operation/           # 申购、赎回、转账等业务操作接口
│   │   ├── risk/                # 风控监测与预警接口
│   │   ├── workorder/           # 工单管理接口
│   │   └── admin/               # 系统管理接口
│   ├── config/                  # 环境、数据库、模型及系统参数配置
│   ├── dao/                     # Data Access Object 数据访问层
│   │   ├── mysql/               # MySQL 业务数据访问
│   │   ├── redis/               # Redis 会话、缓存及事件数据访问
│   │   ├── milvus/              # Milvus 向量数据访问
│   │   ├── neo4j/               # Neo4j 图谱数据访问
│   │   └── minio/               # MinIO 对象存储访问
│   ├── event/                   # Redis Pub/Sub 事件发布、订阅与处理
│   ├── models/                  # MVC 的 Model 层
│   │   ├── entities/            # 数据库 ORM 实体
│   │   └── schemas/             # Pydantic 请求、响应及 DTO 模型
│   ├── service/                 # 业务逻辑与核心能力实现层
│   │   ├── rag/                 # RAG 检索增强生成流程
│   │   ├── graphrag/            # GraphRAG 图谱增强检索流程
│   │   ├── nl2sql/              # 自然语言转 SQL
│   │   ├── nl2api/              # 自然语言转 API 调用
│   │   ├── memory/              # 短期、中期及长期记忆体系
│   │   ├── confidence/          # 置信度计算与重排
│   │   └── risk/                # 风控规则及预警业务逻辑
│   ├── tool/                    # Agent 可调用的标准化工具层
│   │   ├── document/            # 文档解析工具
│   │   ├── embedding/           # 向量化工具
│   │   ├── retrieval/           # 知识检索工具
│   │   ├── graph/               # 图谱查询工具
│   │   ├── sql/                 # SQL 生成、校验及执行工具
│   │   ├── operation/           # 业务操作工具
│   │   ├── memory/              # 记忆读写与校验工具
│   │   ├── profile/             # 客户画像工具
│   │   └── risk/                # 风险规则匹配工具
│   ├── utils/                   # 日志、异常、时间、ID 等通用辅助能力
│   └── view/                    # MVC 的 View 层
│       ├── streamlit/           # Streamlit 展示界面
│       ├── gradio/              # Gradio 展示界面
│       └── response/            # 响应数据的展示与格式化
├── docs/                        # 需求、设计、规则、政策和测试资料
├── tests/                       # 自动化测试
│   ├── unit/                    # 单元测试
│   ├── integration/             # 数据库及组件集成测试
│   └── e2e/                     # 端到端业务流程测试
├── .gitignore                   # Git 忽略规则
└── README.md                    # 项目说明
```

## 分层关系

本项目采用 MVC 与 Agent 分层结合的结构：

- `models` 是 Model，定义系统使用的数据结构。
- `view` 是 View，负责页面和结果展示。
- `api` 承担 Controller 职责，接收请求并调用相应业务能力。
- `agent` 负责理解意图、召回记忆、选择工具和编排执行流程。
- `service` 负责实现可复用的业务流程。
- `tool` 将检索、查询、规则和操作能力包装成 Agent 可调用的统一工具。
- `dao` 隔离底层数据库和存储的访问细节。
- `event` 通过 Redis Pub/Sub 实现 Agent 之间的异步协作。

典型调用流程如下：

```text
View → API → Agent / Service → Tool → DAO → 数据库或存储
```

例如，一次金融产品咨询的处理流程为：

```text
Streamlit → Chat API → 智能客服 Agent → RAG Service
→ Knowledge Retrieval Tool → Milvus DAO → 返回带来源引用的回答
```

## 目录占位说明

当前项目处于框架初始化阶段。空目录中的 `.gitkeep` 是 Git 目录占位文件，不包含业务逻辑；目录内加入正式代码后，可以删除对应的 `.gitkeep`。

`docs/` 和 `.idea/` 已配置为本地忽略目录，不会随 Git 提交上传。
