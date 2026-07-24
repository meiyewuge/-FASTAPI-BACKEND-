-- DSM W3-01 identity chain rollback (SQLite dialect). Idempotent.
-- WARNING: DESTRUCTIVE — drops all identity tables/sessions/bindings/users, the
-- store registry, and the schema-version row. SQLite triggers drop automatically
-- with their tables, so no extra trigger cleanup is needed. Contains NO
-- PostgreSQL-only statements. Only run to undo the W3-01 identity migration.
DROP INDEX IF EXISTS ix_dl_session_user;
DROP INDEX IF EXISTS uq_dl_session_token_hash;
DROP TABLE IF EXISTS dl_auth_session;

DROP INDEX IF EXISTS ix_dl_binding_store;
DROP INDEX IF EXISTS uq_dl_binding_store_authuser;
DROP INDEX IF EXISTS uq_dl_binding_store_member;
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
