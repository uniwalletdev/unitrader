-- ──────────────────────────────────────────────────────────────────────────
-- 005_etoro_support.sql — eToro exchange support (Phase B1)
--
-- Adds `etoro_environment` (demo|real) column to `exchange_api_keys` so a
-- single user can have one eToro credential row but select whether the
-- Trust Ladder routes orders to eToro Demo or Real when executing.
--
-- Existing columns re-used:
--   exchange_api_keys.encrypted_api_key     → eToro user_key   (Fernet)
--   exchange_api_keys.encrypted_api_secret  → eToro api_key_id (Fernet)
--   exchange_api_keys.is_paper              → true when etoro_environment='demo'
--   exchange_api_keys.exchange              → 'etoro'
--
-- No new credential storage scheme introduced. Fernet parity with
-- Alpaca/Coinbase/Kraken/OANDA/Binance.
--
-- Apply in Supabase SQL editor AFTER 004_execution_mode.sql.
-- Idempotent — safe to re-run. Run each statement sequentially (do NOT
-- combine ALTER statements — that caused deadlocks in past migrations).
-- ──────────────────────────────────────────────────────────────────────────

-- (a) Add the environment column -------------------------------------------
ALTER TABLE exchange_api_keys
    ADD COLUMN IF NOT EXISTS etoro_environment TEXT;

-- (b) Constrain values (NULL allowed for non-eToro rows) -------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
         WHERE table_name = 'exchange_api_keys'
           AND constraint_name = 'etoro_environment_chk'
    ) THEN
        EXECUTE 'ALTER TABLE exchange_api_keys
                 ADD CONSTRAINT etoro_environment_chk
                 CHECK (etoro_environment IS NULL OR etoro_environment IN (''demo'',''real''))';
    END IF;
END $$;

-- (c) Back-fill: if a user somehow already has an eToro row without env,
--     default to demo (safest).
UPDATE exchange_api_keys
   SET etoro_environment = 'demo'
 WHERE exchange = 'etoro'
   AND etoro_environment IS NULL;

-- Verification
-- SELECT exchange, is_paper, etoro_environment
--   FROM exchange_api_keys
--  WHERE exchange = 'etoro' LIMIT 20;
