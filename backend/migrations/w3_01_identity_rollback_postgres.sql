-- DSM W3-01 identity chain rollback (PostgreSQL dialect). Idempotent.
-- WARNING: DESTRUCTIVE — drops all identity tables/sessions/bindings/users, the
-- store registry, the schema-version row, AND the status-epoch trigger function.
-- Triggers drop with their tables; the function must be dropped explicitly.
-- NOTE: not executed against a real PostgreSQL in this environment
-- (POSTGRES_RUNTIME_NOT_EXECUTED); reviewed DDL.
DROP INDEX IF EXISTS ix_dl_session_user;
DROP INDEX IF EXISTS uq_dl_session_token_hash;
DROP TABLE IF EXISTS dl_auth_session;

DROP INDEX IF EXISTS ix_dl_binding_store;
DROP INDEX IF EXISTS uq_dl_binding_member_public_id;
DROP INDEX IF EXISTS uq_dl_binding_app_user;
DROP TABLE IF EXISTS dl_store_member_binding;

DROP INDEX IF EXISTS uq_dl_wechat_app_user;
DROP INDEX IF EXISTS uq_dl_wechat_openid_hash;
DROP TABLE IF EXISTS dl_wechat_identity;

DROP TABLE IF EXISTS dl_app_user;

DROP INDEX IF EXISTS uq_dl_store_v013_store_id;
DROP INDEX IF EXISTS uq_dl_store_main_store_id;
DROP INDEX IF EXISTS uq_dl_store_dl_store_id;
DROP INDEX IF EXISTS uq_dl_store_public_id;
DROP TABLE IF EXISTS dl_store_registry;

DROP TABLE IF EXISTS dl_identity_schema_meta;

DROP FUNCTION IF EXISTS dl_bump_status_epoch();
