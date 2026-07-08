-- P0B-2 Migration: Add access_token to diagnoses and monthly_checkups
-- Version: V0.2.0-P0B-2
-- Date: 2026-07-08
-- Status: DRAFT ONLY - DO NOT EXECUTE
--
-- IMPORTANT: This migration MUST be executed BEFORE deploying P0B-2 code.
-- Execution order:
--   1. Backup database
--   2. Execute this SQL
--   3. Verify schema
--   4. Deploy backend code
--   5. Deploy frontend code
--
-- Risk: If code deploys before DB migration, you will get "no such column: access_token" errors.

-- 1. Add access_token to diagnoses table
ALTER TABLE diagnoses ADD COLUMN access_token VARCHAR(64);

-- 2. Add access_token to monthly_checkups table
ALTER TABLE monthly_checkups ADD COLUMN access_token VARCHAR(64);

-- 3. Create index for faster token lookups (optional but recommended)
CREATE INDEX IF NOT EXISTS idx_diagnoses_access_token ON diagnoses(access_token);
CREATE INDEX IF NOT EXISTS idx_monthly_checkups_access_token ON monthly_checkups(access_token);

-- Verification queries (run after migration):
-- SELECT COUNT(*) FROM diagnoses WHERE access_token IS NULL;
-- SELECT COUNT(*) FROM monthly_checkups WHERE access_token IS NULL;
-- SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%access_token';

-- Notes:
-- - Old records (created before P0B-2) will have access_token = NULL
-- - New records will have access_token = 64-char hex string
-- - allow_unauthenticated_results = True (default) allows old records to be accessed without token
-- - P0B-5 will close the compatibility period (allow_unauthenticated_results = False)
