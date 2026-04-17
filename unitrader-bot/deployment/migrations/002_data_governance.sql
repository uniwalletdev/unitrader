-- ============================================================================
-- Phase 12 — Data Governance + Business Ops
--
-- Creates 4 tables:
--   • egress_allowlist    — domains allowed to receive outbound HTTP
--   • egress_audit_log    — every outbound call (audit trail)
--   • business_approvals  — approval queue for any egress outside allowlist
--   • business_snapshots  — hourly MRR / cost / margin / forecast snapshots
--
-- Seeds the allowlist with currently-integrated third parties
-- (all pre-approved because you already use them) and reserves
-- `api.hmrc.gov.uk` as `must_approve` for future MTD integration.
--
-- Idempotent: safe to re-run.
-- ============================================================================

-- ── 1. Egress allowlist ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS egress_allowlist (
    domain          TEXT PRIMARY KEY,
    category        TEXT NOT NULL CHECK (category IN ('read_only','read_write','must_approve')),
    purpose         TEXT NOT NULL,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by        TEXT
);

-- Seed pre-approved integrations (idempotent via ON CONFLICT).
INSERT INTO egress_allowlist (domain, category, purpose, added_by) VALUES
    ('api.stripe.com',                  'read_write',   'Payments & subscriptions',      'seed'),
    ('api.anthropic.com',               'read_write',   'Claude LLM API',                 'seed'),
    ('api.openai.com',                  'read_write',   'OpenAI fallback',                'seed'),
    ('api.resend.com',                  'read_write',   'Transactional email',            'seed'),
    ('o4504543068880896.ingest.sentry.io','read_write', 'Sentry error tracking',          'seed'),
    ('paper-api.alpaca.markets',        'read_write',   'Alpaca paper trading',           'seed'),
    ('api.alpaca.markets',              'read_write',   'Alpaca live trading',            'seed'),
    ('data.alpaca.markets',             'read_only',    'Alpaca market data',             'seed'),
    ('api.coinbase.com',                'read_write',   'Coinbase Advanced Trade',        'seed'),
    ('ws-feed.exchange.coinbase.com',   'read_only',    'Coinbase WebSocket feed',        'seed'),
    ('api.binance.com',                 'read_write',   'Binance trading',                'seed'),
    ('api.kraken.com',                  'read_write',   'Kraken trading',                 'seed'),
    ('query1.finance.yahoo.com',        'read_only',    'Yahoo Finance historicals',      'seed'),
    ('api.telegram.org',                'read_write',   'Telegram bot',                   'seed'),
    ('graph.facebook.com',              'read_write',   'WhatsApp Cloud API',             'seed'),
    ('api.clerk.dev',                   'read_write',   'Clerk auth',                     'seed'),
    ('api.clerk.com',                   'read_write',   'Clerk auth (new)',               'seed'),
    ('api.railway.app',                 'read_only',    'Railway hosting (cost/logs)',    'seed'),
    ('api.vercel.com',                  'read_only',    'Vercel (cost/bandwidth)',        'seed'),
    -- HMRC reserved (must_approve) — any future MTD call will queue for approval.
    ('api.hmrc.gov.uk',                 'must_approve', 'HMRC Making Tax Digital (reserved)', 'seed'),
    ('test-api.service.hmrc.gov.uk',    'must_approve', 'HMRC MTD sandbox (reserved)',    'seed')
ON CONFLICT (domain) DO NOTHING;


-- ── 2. Egress audit log ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS egress_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    domain          TEXT NOT NULL,
    method          TEXT NOT NULL,
    path            TEXT,
    status_code     INTEGER,
    purpose         TEXT,
    bytes_out       INTEGER DEFAULT 0,
    bytes_in        INTEGER DEFAULT 0,
    duration_ms     INTEGER,
    approval_id     UUID,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_egress_audit_ts     ON egress_audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_egress_audit_domain ON egress_audit_log (domain, ts DESC);


-- ── 3. Business approvals ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS business_approvals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requested_by_agent  TEXT NOT NULL,
    action_category     TEXT NOT NULL CHECK (action_category IN (
        'egress','hmrc_filing','investigation','external_notification','data_export'
    )),
    target_domain       TEXT,
    action_summary      TEXT NOT NULL,
    request_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending','approved','denied','executed','failed','expired'
    )),
    result_payload      JSONB,
    notified_via        TEXT[] DEFAULT ARRAY[]::TEXT[],
    approved_at         TIMESTAMPTZ,
    approved_via        TEXT,
    executed_at         TIMESTAMPTZ,
    denial_reason       TEXT,
    ttl_expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_approvals_status     ON business_approvals (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_created_at ON business_approvals (created_at DESC);


-- ── 4. Business snapshots ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS business_snapshots (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mrr_cents               BIGINT NOT NULL DEFAULT 0,
    active_subs             INTEGER NOT NULL DEFAULT 0,
    new_subs_30d            INTEGER NOT NULL DEFAULT 0,
    cancelled_subs_30d      INTEGER NOT NULL DEFAULT 0,
    churn_rate_pct          NUMERIC(5,2) NOT NULL DEFAULT 0,
    costs_total_cents       BIGINT NOT NULL DEFAULT 0,
    costs_breakdown         JSONB NOT NULL DEFAULT '{}'::jsonb,
    margin_cents            BIGINT NOT NULL DEFAULT 0,
    forecast_30d_mrr_cents  BIGINT,
    forecast_30d_cost_cents BIGINT,
    anomalies               JSONB DEFAULT '[]'::jsonb,
    notes                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_at ON business_snapshots (snapshot_at DESC);


-- ── Verification queries ───────────────────────────────────────────────────
-- SELECT domain, category FROM egress_allowlist ORDER BY category, domain;
-- SELECT COUNT(*) FROM business_snapshots;
