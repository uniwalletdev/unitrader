-- ─────────────────────────────────────────────────────────────────────────────
-- 007_haiku_4_5_fallback.sql
--
-- Migrate token_optimizer_config.fallback_model rows off the retired
-- claude-3-haiku-20240307 (deprecated by Anthropic 2026-04-20) onto
-- claude-haiku-4-5-20251001. Forward-only; safe to re-run (idempotent).
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE token_optimizer_config
SET fallback_model = 'claude-haiku-4-5-20251001',
    updated_at     = NOW()
WHERE fallback_model = 'claude-3-haiku-20240307';

-- Update the column default for future inserts.
ALTER TABLE token_optimizer_config
    ALTER COLUMN fallback_model SET DEFAULT 'claude-haiku-4-5-20251001';
