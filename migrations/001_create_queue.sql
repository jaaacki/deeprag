-- Migration 001: Create processing queue table
-- Status flow: pending -> processing -> moved -> emby_pending -> completed (or error at any stage)

CREATE TABLE IF NOT EXISTS processing_queue (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL,
    movie_code      VARCHAR(20),
    actress         VARCHAR(255),
    subtitle        VARCHAR(50),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    new_path        TEXT,
    emby_item_id    VARCHAR(100),
    metadata_json   JSONB,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    next_retry_at   TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index on status for queue polling queries
CREATE INDEX IF NOT EXISTS idx_queue_status ON processing_queue (status);

-- Index on next_retry_at for retry polling
CREATE INDEX IF NOT EXISTS idx_queue_retry ON processing_queue (next_retry_at)
    WHERE status = 'error' AND next_retry_at IS NOT NULL;

-- Index on file_path to prevent duplicate entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_file_path ON processing_queue (file_path);

-- Trigger to auto-update updated_at on row changes
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_queue_updated_at ON processing_queue;
CREATE TRIGGER trg_queue_updated_at
    BEFORE UPDATE ON processing_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
