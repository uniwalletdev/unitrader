-- ──────────────────────────────────────────────────────────────────────────
-- 006_etoro_offer_card.sql — eToro offer card dismissal timestamp (Phase B1)
--
-- Adds a single nullable TIMESTAMPTZ column to `user_settings` so the
-- backend can answer "should the eToro offer card render for this user?"
-- with a null check. Both Accept and Dismiss set the timestamp — once
-- written, the card never reappears for that user.
--
-- No DB-level enum; telemetry (etoro_offer_card_{shown,accepted,dismissed})
-- captures the finer-grained state for analytics.
--
-- Apply in Supabase SQL editor AFTER 005_etoro_support.sql.
-- Idempotent — safe to re-run. Run each statement sequentially.
-- ──────────────────────────────────────────────────────────────────────────

-- (a) Add the dismissal timestamp column ------------------------------------
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS etoro_offer_dismissed_at TIMESTAMPTZ;

-- Verification
-- SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--  WHERE table_name = 'user_settings'
--    AND column_name = 'etoro_offer_dismissed_at';
