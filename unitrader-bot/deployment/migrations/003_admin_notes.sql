-- ──────────────────────────────────────────────────────────────────────────
-- 003_admin_notes.sql — Phase 13 backoffice: support notes per user
--
-- Apply in Supabase SQL editor AFTER 002_data_governance.sql.
-- Idempotent — safe to re-run.
-- ──────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS admin_user_notes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    author      VARCHAR(120) NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_notes_user_created
    ON admin_user_notes (user_id, created_at DESC);

-- Verification
-- SELECT COUNT(*) FROM admin_user_notes;
