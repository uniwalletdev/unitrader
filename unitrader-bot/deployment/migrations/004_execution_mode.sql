-- ──────────────────────────────────────────────────────────────────────────
-- 004_execution_mode.sql — Execution Mode × Trust Ladder refactor
--
-- Renames UserSettings.signal_stack_mode → execution_mode and migrates the
-- three legacy values (browse/apex_selects/full_auto) to the new 4-value
-- taxonomy (watch/assisted/guided/autonomous). Adds the unified
-- guided_confidence_threshold column (replacing apex_selects_threshold) and
-- the autonomous opt-in columns.
--
-- Apply in Supabase SQL editor AFTER 003_admin_notes.sql.
-- Idempotent — safe to re-run. Run statements sequentially.
-- ──────────────────────────────────────────────────────────────────────────

-- (a) Rename + migrate execution mode values -------------------------------
UPDATE user_settings SET signal_stack_mode = 'watch'      WHERE signal_stack_mode = 'browse';
UPDATE user_settings SET signal_stack_mode = 'assisted'   WHERE signal_stack_mode = 'apex_selects';
UPDATE user_settings SET signal_stack_mode = 'autonomous' WHERE signal_stack_mode = 'full_auto';

-- Rename the column (guarded for re-runs)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'user_settings' AND column_name = 'signal_stack_mode'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'user_settings' AND column_name = 'execution_mode'
    ) THEN
        EXECUTE 'ALTER TABLE user_settings RENAME COLUMN signal_stack_mode TO execution_mode';
    END IF;
END $$;

-- (b) Unified confidence threshold (replaces apex_selects_threshold) -------
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS guided_confidence_threshold INT NOT NULL DEFAULT 70;

-- Seed from the legacy column if it still exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'user_settings' AND column_name = 'apex_selects_threshold'
    ) THEN
        EXECUTE 'UPDATE user_settings SET guided_confidence_threshold = apex_selects_threshold
                  WHERE apex_selects_threshold IS NOT NULL';
        EXECUTE 'ALTER TABLE user_settings DROP COLUMN apex_selects_threshold';
    END IF;
END $$;

-- (c) Autonomous opt-in columns --------------------------------------------
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS autonomous_mode_unlocked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS autonomous_unlocked_at TIMESTAMPTZ;

-- Verification
-- SELECT execution_mode, guided_confidence_threshold,
--        autonomous_mode_unlocked, autonomous_unlocked_at
--   FROM user_settings LIMIT 5;
