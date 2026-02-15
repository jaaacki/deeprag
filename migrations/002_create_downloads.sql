-- Migration 002: Create download jobs table
-- Status flow: queued -> downloading -> completed/failed

CREATE TABLE IF NOT EXISTS download_jobs (
    id              SERIAL PRIMARY KEY,
    url             TEXT NOT NULL,
    filename        VARCHAR(500),
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    error           TEXT,
    output_tail     JSONB DEFAULT '[]'::jsonb,
    started_at      TIMESTAMP WITH TIME ZONE,
    finished_at     TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index on status for filtering
CREATE INDEX IF NOT EXISTS idx_downloads_status ON download_jobs(status);

-- Index on created_at for listing recent downloads
CREATE INDEX IF NOT EXISTS idx_downloads_created ON download_jobs(created_at);

-- Reuse the update_updated_at_column() function from migration 001
DROP TRIGGER IF EXISTS trg_downloads_updated_at ON download_jobs;
CREATE TRIGGER trg_downloads_updated_at
    BEFORE UPDATE ON download_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
