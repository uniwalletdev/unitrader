-- ============================================================================
-- Migration: Token Management Agent (Phase 0C)
-- Run in Supabase SQL Editor.
--
-- NOTE: This project uses VARCHAR(36) for user IDs (not auth.users UUID).
--       All user_id FKs must match that type.
-- ============================================================================

-- ────────────────────────────────────────────────────────────────────────────
-- 1. token_audit_log — immutable ledger of every Anthropic API call
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_name      VARCHAR(64) NOT NULL,
    task_type       VARCHAR(64),
    model           VARCHAR(64) NOT NULL,
    tokens_in       INT NOT NULL DEFAULT 0,
    tokens_out      INT NOT NULL DEFAULT 0,
    cached_tokens   INT NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12, 8) NOT NULL DEFAULT 0,
    latency_ms      INT,
    cache_hit       BOOLEAN NOT NULL DEFAULT FALSE,
    user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    trade_id        VARCHAR(36),
    status          VARCHAR(24) NOT NULL DEFAULT 'success',
    error_message   TEXT,
    context_hash    VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_audit_agent_time
    ON token_audit_log (agent_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_token_audit_user_time
    ON token_audit_log (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_token_audit_month
    ON token_audit_log (DATE_TRUNC('month', timestamp), agent_name);


-- ────────────────────────────────────────────────────────────────────────────
-- 2. token_budget — monthly allocation + alert state
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_budget (
    id              BIGSERIAL PRIMARY KEY,
    month_start     DATE NOT NULL UNIQUE,
    month_end       DATE NOT NULL,
    budget_total    BIGINT NOT NULL DEFAULT 10000000,   -- 10M tokens default
    budget_used     BIGINT NOT NULL DEFAULT 0,
    cost_total_usd  NUMERIC(12, 4) NOT NULL DEFAULT 0,
    alert_70_sent   BOOLEAN NOT NULL DEFAULT FALSE,
    alert_85_sent   BOOLEAN NOT NULL DEFAULT FALSE,
    alert_95_sent   BOOLEAN NOT NULL DEFAULT FALSE,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_budget_status
    ON token_budget (status, month_start DESC);


-- ────────────────────────────────────────────────────────────────────────────
-- 3. agent_rate_limits — per-agent token-bucket throttling
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_rate_limits (
    id                          BIGSERIAL PRIMARY KEY,
    agent_name                  VARCHAR(64) UNIQUE NOT NULL,
    tokens_per_minute           INT NOT NULL DEFAULT 2000,
    tokens_used_this_minute     INT NOT NULL DEFAULT 0,
    last_reset                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    priority                    VARCHAR(4) NOT NULL DEFAULT 'p1',   -- p0 | p1 | p2
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ────────────────────────────────────────────────────────────────────────────
-- 4. token_optimizer_config — per-agent context/fallback config
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_optimizer_config (
    id                  BIGSERIAL PRIMARY KEY,
    agent_name          VARCHAR(64) UNIQUE NOT NULL,
    context_max_tokens  INT NOT NULL DEFAULT 4000,
    trim_strategy       VARCHAR(32) NOT NULL DEFAULT 'sliding_window',
    fallback_model      VARCHAR(64) NOT NULL DEFAULT 'claude-3-haiku-20240307',
    enabled_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ────────────────────────────────────────────────────────────────────────────
-- 5. Seed: initial month's budget row
-- ────────────────────────────────────────────────────────────────────────────
INSERT INTO token_budget (month_start, month_end, budget_total, status)
VALUES (
    DATE_TRUNC('month', NOW())::DATE,
    (DATE_TRUNC('month', NOW()) + INTERVAL '1 month - 1 day')::DATE,
    10000000,
    'active'
)
ON CONFLICT (month_start) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 6. Seed: agent rate limits for every agent actually present in the repo
--    Priorities:
--      p0 = never throttled (real-money critical path)
--      p1 = throttle if budget > 85%
--      p2 = pause if budget > 85% (batch / non-urgent)
-- ────────────────────────────────────────────────────────────────────────────
INSERT INTO agent_rate_limits (agent_name, tokens_per_minute, priority) VALUES
    ('trading',         3000, 'p0'),
    ('conversation',    2000, 'p1'),
    ('portfolio',       1500, 'p1'),
    ('sentiment',       1000, 'p1'),
    ('signal_stack',    2000, 'p1'),
    ('content_writer',  1500, 'p2'),
    ('social_media',    1500, 'p2'),
    ('learning_hub',    1000, 'p2'),
    ('token_manager',    500, 'p0')
ON CONFLICT (agent_name) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 7. Seed: optimizer config defaults
-- ────────────────────────────────────────────────────────────────────────────
INSERT INTO token_optimizer_config (agent_name, context_max_tokens, fallback_model) VALUES
    ('trading',         4000, 'claude-3-haiku-20240307'),
    ('conversation',    6000, 'claude-3-haiku-20240307'),
    ('portfolio',       3000, 'claude-3-haiku-20240307'),
    ('sentiment',       2000, 'claude-3-haiku-20240307'),
    ('signal_stack',    3000, 'claude-3-haiku-20240307'),
    ('content_writer',  8000, 'claude-3-haiku-20240307'),
    ('social_media',    4000, 'claude-3-haiku-20240307'),
    ('learning_hub',    6000, 'claude-3-haiku-20240307')
ON CONFLICT (agent_name) DO NOTHING;
