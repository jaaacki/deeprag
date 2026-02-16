CREATE TABLE IF NOT EXISTS auth_tokens (
    id           SERIAL PRIMARY KEY,
    access_token TEXT NOT NULL,
    expires_at   TIMESTAMP WITH TIME ZONE,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_created ON auth_tokens (created_at DESC);
