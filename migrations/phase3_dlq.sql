-- Phase 3.1 DLQ (dead letter queue) for Kafka poison batches.
-- When a Kafka batch fails processing, write the failed message_ids
-- to this table before committing the offset, so the daemon can move
-- past the poison message and operators can inspect/replay later.
CREATE TABLE IF NOT EXISTS antiblack.kafka_dead_letter_queue (
    id BIGSERIAL PRIMARY KEY,
    topic VARCHAR(128) NOT NULL,
    partition_id INT NOT NULL,
    kafka_offset BIGINT NOT NULL,
    message_id TEXT,
    payload JSONB,
    error_msg TEXT,
    failed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    retry_count INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dlq_failed_at
    ON antiblack.kafka_dead_letter_queue(failed_at DESC);
CREATE INDEX IF NOT EXISTS idx_dlq_message_id
    ON antiblack.kafka_dead_letter_queue(message_id);
