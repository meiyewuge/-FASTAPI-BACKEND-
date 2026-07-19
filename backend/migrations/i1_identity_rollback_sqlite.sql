-- Stage I1-R1b rollback (SQLite dialect). Idempotent.
-- WARNING: DESTRUCTIVE — drops all identity tables/sessions/bindings/users and
-- the schema-version row. SQLite triggers are dropped automatically with their
-- tables, so no extra trigger cleanup is needed here. Contains NO PostgreSQL-only
-- statements. Only run to undo the I1 identity migration.
DROP INDEX IF EXISTS ix_dl_session_user;
DROP INDEX IF EXISTS uq_dl_session_token_hash;
DROP TABLE IF EXISTS dl_auth_session;

DROP INDEX IF EXISTS ix_dl_binding_store;
DROP INDEX IF EXISTS uq_dl_binding_app_user;
DROP TABLE IF EXISTS dl_store_member_binding;

DROP INDEX IF EXISTS uq_dl_wechat_app_user;
DROP INDEX IF EXISTS uq_dl_wechat_openid_hash;
DROP TABLE IF EXISTS dl_wechat_identity;

DROP TABLE IF EXISTS dl_app_user;
DROP TABLE IF EXISTS dl_identity_schema_meta;
