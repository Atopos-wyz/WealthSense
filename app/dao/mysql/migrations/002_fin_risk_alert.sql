-- 风控预警表（仅本模块；与 RiskAlertEntity 对齐）
-- 本地执行示例（DBeaver 连 root@127.0.0.1:3306）：
--   1) 先执行下方 CREATE DATABASE（若已有 finance 可跳过）
--   2) 选中 finance 库后再执行 CREATE TABLE
-- 不要用 metadata.create_all 在生产建表。

CREATE DATABASE IF NOT EXISTS finance
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE finance;

CREATE TABLE IF NOT EXISTS fin_risk_alert (
    id              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '预警 ID = 事件 alert_id',
    customer_id     VARCHAR(64)  NOT NULL COMMENT '客户标识',
    record_type     VARCHAR(32)  NOT NULL COMMENT 'alert | audit_clean',
    alert_level     VARCHAR(8)   NULL DEFAULT NULL COMMENT '低/中/高',
    hit_rules_json  TEXT         NOT NULL COMMENT '命中规则 JSON',
    reason          TEXT         NULL DEFAULT NULL COMMENT '原因摘要',
    confidence      FLOAT        NOT NULL DEFAULT 0 COMMENT '置信度',
    llm_review      VARCHAR(64)  NULL DEFAULT NULL COMMENT '同意规则|建议人工复核|可疑|null',
    llm_conflict    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '模型是否与规则冲突',
    status          VARCHAR(32)  NOT NULL DEFAULT '未处理' COMMENT '未处理|已确认|已排除等',
    work_order_id   VARCHAR(64)  NULL DEFAULT NULL COMMENT '中高：WO-{id}',
    broadcasted     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否已走广播分支',
    created_at      DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
    PRIMARY KEY (id),
    KEY ix_fin_risk_alert_customer_id (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AML 风控预警/审计落库';
