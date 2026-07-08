# P0B-2 Migration Guide

## Overview

This migration adds `access_token` column to `diagnoses` and `monthly_checkups` tables for P0B-2 result page authentication.

## Files

- `p0b2_add_access_token.sql` — SQL migration script (DRAFT ONLY, not executed)

## Execution Order (P0B-2 Deployment)

**CRITICAL**: DB migration MUST be executed BEFORE deploying backend code.

```
1. Backup database
   - SQLite: cp storecoach.db storecoach.db.bak
   - PostgreSQL: pg_dump > backup.sql

2. Execute migration SQL
   - sqlite3 storecoach.db < p0b2_add_access_token.sql
   - psql dbname < p0b2_add_access_token.sql

3. Verify schema
   - Check access_token column exists in diagnoses
   - Check access_token column exists in monthly_checkups
   - Check indexes created

4. Deploy backend code
   - models.py (access_token column)
   - config.py (allow_unauthenticated_results)
   - auth.py (verify_result_auth, verify_store_auth)
   - diagnoses.py (token generation + auth)
   - monthly.py (token generation + auth + 409 fix)

5. Deploy frontend code
   - DiagnosisForm.vue (token in redirect)
   - DiagnosisResult.vue (token read + upgrade)
   - MonthlyForm.vue (token in redirect + 409 handling)
   - MonthlyResult.vue (token read + upgrade)
   - Trends.vue (token read)

6. Smoke test
   - POST diagnosis → get access_token
   - GET diagnosis with token → 200
   - GET diagnosis without token → 200 (legacy) or 401 (new)
   - 409 monthly → only message + store_id + check_month
```

## Verification Queries

```sql
-- Check access_token column exists
SELECT name FROM pragma_table_info('diagnoses') WHERE name='access_token';
SELECT name FROM pragma_table_info('monthly_checkups') WHERE name='access_token';

-- Count old records (access_token=NULL)
SELECT COUNT(*) FROM diagnoses WHERE access_token IS NULL;
SELECT COUNT(*) FROM monthly_checkups WHERE access_token IS NULL;

-- Count indexes
SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%access_token';
```

## Rollback Plan

If deployment fails:

1. Restore database from backup
2. Revert backend code to previous version
3. Revert frontend code to previous version

## Compatibility Period

- `allow_unauthenticated_results = True` (default): Old records (access_token=NULL) can be accessed without token
- `allow_unauthenticated_results = False` (P0B-5): All records require token

## Notes

- Old records created before P0B-2 will have `access_token = NULL`
- New records created after P0B-2 will have `access_token = 64-char hex string`
- No data backfill for old records (they remain NULL)
