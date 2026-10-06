CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT 'Answer the user using the connected company handbook. Be clear, concise, and cite source files.',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY,
    org_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    requested_by TEXT NOT NULL,
    task TEXT NOT NULL,
    agent_instructions TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE REFERENCES runs(id),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs (created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS runs_scope_idx ON runs (org_id, workspace_id, created_at DESC);
