"""WealthSense 客户画像域的 MySQL 建表语句。

本模块只负责数据库结构定义，不包含业务逻辑。表结构来自
《投顾Agent客户画像生成_意图路由与更新机制实施框架》。

画像主表刻意不包含 ``risk_score``。D1-D4 和综合分数保存在
``fin_profile_evaluation`` 中。
"""

from collections.abc import Awaitable, Callable, Iterator


SYS_USER_DDL = """
CREATE TABLE IF NOT EXISTS sys_user (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '用户ID',
    user_no VARCHAR(64) NULL COMMENT '用户业务编号',
    phone VARCHAR(32) NULL COMMENT '注册手机号',
    email VARCHAR(128) NULL COMMENT '注册邮箱',
    password_hash VARCHAR(255) NULL COMMENT '密码摘要，不保存明文密码',
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT '用户状态',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_sys_user_no (user_no),
    UNIQUE KEY uk_sys_user_phone (phone),
    UNIQUE KEY uk_sys_user_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='系统用户';
""".strip()


FIN_PRODUCT_DDL = """
CREATE TABLE IF NOT EXISTS fin_product (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '产品ID',
    product_code VARCHAR(64) NOT NULL COMMENT '产品编码',
    product_name VARCHAR(128) NOT NULL COMMENT '产品名称',
    product_type VARCHAR(32) NOT NULL COMMENT '产品类型，用于资产配置聚合',
    risk_level VARCHAR(16) NULL COMMENT '产品风险等级',
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' COMMENT '产品状态',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_fin_product_code (product_code),
    KEY idx_fin_product_type_status (product_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='金融产品基础信息';
""".strip()


FIN_RISK_ASSESSMENT_DDL = """
CREATE TABLE IF NOT EXISTS fin_risk_assessment (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '风险测评ID',
    assessment_no VARCHAR(64) NOT NULL COMMENT '风险测评业务编号',
    customer_id BIGINT NOT NULL COMMENT '客户ID',
    assessment_date DATETIME NOT NULL COMMENT '测评时间',
    total_score DECIMAL(5,2) NOT NULL COMMENT '正式问卷分数，范围0-100',
    risk_level VARCHAR(16) NOT NULL COMMENT '正式风险等级',
    answers JSON NOT NULL COMMENT '问卷答案',
    assessor_type VARCHAR(16) NOT NULL COMMENT '评估方式：AI或人工',
    valid_until DATE NOT NULL COMMENT '有效期截止日期',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_risk_assessment_no (assessment_no),
    KEY idx_risk_assessment_customer_valid (
        customer_id,
        valid_until,
        assessment_date
    ),
    CONSTRAINT fk_risk_assessment_user
        FOREIGN KEY (customer_id) REFERENCES sys_user(id),
    CONSTRAINT chk_risk_assessment_total_score
        CHECK (total_score >= 0 AND total_score <= 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='客户正式风险测评记录';
""".strip()


FIN_HOLDINGS_DDL = """
CREATE TABLE IF NOT EXISTS fin_holdings (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '持仓记录ID',
    customer_id BIGINT NOT NULL COMMENT '客户ID',
    product_id BIGINT NOT NULL COMMENT '产品ID',
    shares DECIMAL(20,6) NOT NULL DEFAULT 0 COMMENT '持有份额',
    cost_amount DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '持仓成本',
    current_value DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '当前市值',
    profit_loss DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '累计盈亏',
    profit_ratio DECIMAL(9,6) NOT NULL DEFAULT 0 COMMENT '累计收益率',
    status VARCHAR(16) NOT NULL COMMENT '持有中、已清仓等持仓状态',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_holdings_customer_status (customer_id, status),
    KEY idx_holdings_product (product_id),
    CONSTRAINT fk_holdings_user
        FOREIGN KEY (customer_id) REFERENCES sys_user(id),
    CONSTRAINT fk_holdings_product
        FOREIGN KEY (product_id) REFERENCES fin_product(id),
    CONSTRAINT chk_holdings_shares
        CHECK (shares >= 0),
    CONSTRAINT chk_holdings_current_value
        CHECK (current_value >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='客户产品持仓';
""".strip()


FIN_CUSTOMER_PROFILE_DDL = """
CREATE TABLE IF NOT EXISTS fin_customer_profile (
    customer_id BIGINT NOT NULL COMMENT '客户ID，与sys_user一对一',
    risk_level VARCHAR(16) NULL COMMENT '正式与模型等级保守合并后的有效等级',
    investment_experience VARCHAR(16) NULL COMMENT '投资经验年限区间',
    annual_income_range VARCHAR(32) NULL COMMENT '家庭年收入区间',
    total_assets DECIMAL(18,2) NULL COMMENT '持仓汇总资产，无持仓时回退KYC申报',
    asset_allocation JSON NULL COMMENT '当前持仓资产配置比例',
    product_preference JSON NULL COMMENT '客户已确认的产品偏好',
    confidence_score DECIMAL(5,2) NOT NULL DEFAULT 0.20
        COMMENT '画像整体置信度',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (customer_id),
    CONSTRAINT fk_customer_profile_user
        FOREIGN KEY (customer_id) REFERENCES sys_user(id),
    CONSTRAINT chk_customer_profile_confidence
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CONSTRAINT chk_customer_profile_total_assets
        CHECK (total_assets IS NULL OR total_assets >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='当前可用的客户画像摘要';
""".strip()


FIN_PROFILE_EVALUATION_DDL = """
CREATE TABLE IF NOT EXISTS fin_profile_evaluation (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '画像评估ID',
    evaluation_no VARCHAR(64) NOT NULL COMMENT '评估业务编号',
    customer_id BIGINT NOT NULL COMMENT '客户ID',
    d1_score DECIMAL(5,2) NOT NULL COMMENT '基础属性得分，范围0-25',
    d2_score DECIMAL(5,2) NOT NULL COMMENT '投资经验得分，范围0-25',
    d3_score DECIMAL(5,2) NOT NULL COMMENT '风险偏好得分，范围0-30',
    d4_score DECIMAL(5,2) NOT NULL COMMENT '行为异常得分，只允许0或20',
    total_score DECIMAL(5,2) NOT NULL COMMENT 'D1+D2+D3+D4综合得分',
    official_risk_level VARCHAR(16) NOT NULL COMMENT '最新有效正式风险等级',
    model_risk_level VARCHAR(16) NOT NULL COMMENT '综合分映射的模型风险等级',
    effective_risk_level VARCHAR(16) NOT NULL COMMENT '保守合并后的有效风险等级',
    assessment_id BIGINT NULL COMMENT '本次评估使用的正式风险测评ID',
    score_detail JSON NOT NULL COMMENT '各评分项计算依据及结果',
    rule_version VARCHAR(32) NOT NULL COMMENT '评分规则版本',
    trigger_type VARCHAR(32) NOT NULL COMMENT '重建触发类型',
    trigger_id VARCHAR(64) NOT NULL COMMENT '幂等触发ID',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_profile_evaluation_no (evaluation_no),
    UNIQUE KEY uk_profile_evaluation_trigger (trigger_id),
    KEY idx_profile_evaluation_customer (customer_id, create_time),
    KEY idx_profile_evaluation_assessment (assessment_id),
    CONSTRAINT fk_profile_evaluation_user
        FOREIGN KEY (customer_id) REFERENCES sys_user(id),
    CONSTRAINT fk_profile_evaluation_assessment
        FOREIGN KEY (assessment_id) REFERENCES fin_risk_assessment(id),
    CONSTRAINT chk_profile_evaluation_d1
        CHECK (d1_score >= 0 AND d1_score <= 25),
    CONSTRAINT chk_profile_evaluation_d2
        CHECK (d2_score >= 0 AND d2_score <= 25),
    CONSTRAINT chk_profile_evaluation_d3
        CHECK (d3_score >= 0 AND d3_score <= 30),
    CONSTRAINT chk_profile_evaluation_d4
        CHECK (d4_score IN (0, 20)),
    CONSTRAINT chk_profile_evaluation_total
        CHECK (
            total_score = d1_score + d2_score + d3_score + d4_score
            AND total_score >= 0
            AND total_score <= 100
        )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='客户画像四维评分及历史评估';
""".strip()


FIN_PROFILE_FIELD_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS fin_profile_field_audit (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '画像字段审计ID',
    customer_id BIGINT NOT NULL COMMENT '客户ID',
    field_name VARCHAR(64) NOT NULL COMMENT '发生变更或冲突的画像字段',
    old_value JSON NULL COMMENT '变更前字段值',
    new_value JSON NULL COMMENT '本次候选字段值',
    old_source VARCHAR(32) NULL COMMENT '原字段权威来源',
    new_source VARCHAR(32) NOT NULL COMMENT '候选字段来源',
    old_confidence DECIMAL(5,2) NULL COMMENT '原字段置信度',
    new_confidence DECIMAL(5,2) NOT NULL COMMENT '候选字段置信度',
    resolution VARCHAR(16) NOT NULL COMMENT 'APPLIED、REJECTED或CANDIDATE',
    trigger_id VARCHAR(64) NOT NULL COMMENT '本次更新触发ID',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_profile_field_audit_customer_field (
        customer_id,
        field_name,
        create_time
    ),
    KEY idx_profile_field_audit_trigger (trigger_id),
    CONSTRAINT fk_profile_field_audit_user
        FOREIGN KEY (customer_id) REFERENCES sys_user(id),
    CONSTRAINT chk_profile_field_audit_confidence
        CHECK (
            new_confidence >= 0
            AND new_confidence <= 1
            AND (
                old_confidence IS NULL
                OR (old_confidence >= 0 AND old_confidence <= 1)
            )
        ),
    CONSTRAINT chk_profile_field_audit_resolution
        CHECK (resolution IN ('APPLIED', 'REJECTED', 'CANDIDATE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='客户画像字段变更、冲突与来源审计';
""".strip()


FIN_SUITABILITY_CHECK_DDL = """
CREATE TABLE IF NOT EXISTS fin_suitability_check (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '适当性检查ID',
    customer_id BIGINT NOT NULL COMMENT '客户ID',
    product_id BIGINT NOT NULL COMMENT '产品ID',
    customer_risk_level VARCHAR(16) NOT NULL COMMENT '检查时客户风险等级',
    product_risk_level VARCHAR(16) NOT NULL COMMENT '检查时产品风险等级',
    allowed BOOLEAN NOT NULL COMMENT '是否匹配',
    reason VARCHAR(255) NOT NULL COMMENT '匹配结论或拦截原因',
    trace_id VARCHAR(64) NOT NULL COMMENT '调用链路ID',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_suitability_customer_time (customer_id, create_time),
    KEY idx_suitability_product_time (product_id, create_time),
    KEY idx_suitability_allowed_time (allowed, create_time),
    CONSTRAINT fk_suitability_user
        FOREIGN KEY (customer_id) REFERENCES sys_user(id),
    CONSTRAINT fk_suitability_product
        FOREIGN KEY (product_id) REFERENCES fin_product(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='客户与产品适当性检查审计';
""".strip()


# 按外键依赖排序，基础引用表必须先于画像域表创建。
CREATE_TABLE_STATEMENTS: tuple[str, ...] = (
    SYS_USER_DDL,
    FIN_PRODUCT_DDL,
    FIN_RISK_ASSESSMENT_DDL,
    FIN_HOLDINGS_DDL,
    FIN_CUSTOMER_PROFILE_DDL,
    FIN_PROFILE_EVALUATION_DDL,
    FIN_PROFILE_FIELD_AUDIT_DDL,
    FIN_SUITABILITY_CHECK_DDL,
)


def iter_create_table_statements() -> Iterator[str]:
    """按依赖顺序返回客户画像域建表语句。"""

    yield from CREATE_TABLE_STATEMENTS


def render_schema_sql() -> str:
    """将全部建表语句渲染为可直接执行的 SQL 脚本。"""

    return "\n\n".join(CREATE_TABLE_STATEMENTS) + "\n"


async def create_profile_tables(
    execute: Callable[[str], Awaitable[object]],
) -> None:
    """使用调用方提供的异步执行器依次创建表。

    SQLAlchemy ``AsyncConnection`` 可传入 ``exec_driver_sql``；其他数据库
    客户端只需提供接收 SQL 字符串并返回 awaitable 的等价方法。
    事务提交/回滚由调用方管理。
    """

    for statement in CREATE_TABLE_STATEMENTS:
        await execute(statement)
