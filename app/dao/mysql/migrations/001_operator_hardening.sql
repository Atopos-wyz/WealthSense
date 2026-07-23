-- 仅用于已经运行过早期业务操作 Agent 表结构的数据库。
-- 新数据库由 SQLAlchemy create_all 直接创建最终结构，不需要执行本文件。

ALTER TABLE operations
    ADD COLUMN confirmation_expires_at DATETIME(6) NULL;

ALTER TABLE operations
    ADD COLUMN raw_message TEXT NULL;

UPDATE operations
SET raw_message = ''
WHERE raw_message IS NULL;

ALTER TABLE operations
    MODIFY COLUMN raw_message TEXT NOT NULL;

ALTER TABLE operations
    ADD CONSTRAINT uq_operation_source_request
    UNIQUE (source_agent, operator_id, organization_id, request_id);

ALTER TABLE processed_events
    ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'completed';

ALTER TABLE processed_events
    ADD COLUMN lease_expires_at DATETIME(6) NULL;

CREATE TABLE operator_outbox_events (
    id INTEGER NOT NULL AUTO_INCREMENT,
    event_id VARCHAR(64) NOT NULL,
    channel VARCHAR(128) NOT NULL,
    payload_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    sent_at DATETIME(6) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_operator_outbox_event_id (event_id),
    KEY ix_operator_outbox_channel (channel),
    KEY ix_operator_outbox_status (status)
);
