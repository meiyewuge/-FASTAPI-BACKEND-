-- DM Daily Loop V1.1 — Vault Schema (独立数据库)
-- 2张表: dl_identity_vault + dl_vault_access_log
-- 物理独立: vault_v0.db (不与AUTH业务库同文件)
-- 系统服务零访问Vault

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS dl_identity_vault (
    vault_id             TEXT PRIMARY KEY,
    subject_type         TEXT NOT NULL CHECK(subject_type IN ('customer','member')),
    subject_id           TEXT NOT NULL,           -- 假名ID(customer_id或member_id)
    store_id             TEXT NOT NULL,
    encrypted_phone      TEXT,                    -- 加密手机号
    encrypted_name       TEXT,                    -- 加密真实姓名
    encrypted_id_card    TEXT,                    -- 加密证件号
    key_version          TEXT NOT NULL,           -- 密钥版本
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vault_subject ON dl_identity_vault(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_vault_store ON dl_identity_vault(store_id);

CREATE TABLE IF NOT EXISTS dl_vault_access_log (
    access_id            TEXT PRIMARY KEY,
    vault_id             TEXT,  -- no FK: backup/restore logs have empty vault_id
    access_type          TEXT NOT NULL CHECK(access_type IN ('read','write','rotate','recover')),
    access_reason        TEXT NOT NULL,            -- 必填审计理由
    accessor_member_id   TEXT,                     -- 谁访问的(系统服务=None)
    accessor_subject     TEXT NOT NULL CHECK(accessor_subject IN ('manager','owner','reviewer','system','platform_admin','staff')),
    access_result        TEXT NOT NULL CHECK(access_result IN ('granted','denied','error')),
    accessed_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vault_access_vault ON dl_vault_access_log(vault_id);
CREATE INDEX IF NOT EXISTS idx_vault_access_accessor ON dl_vault_access_log(accessor_member_id);

-- 系统服务零访问Vault的CHECK约束:
-- accessor_subject='system'时access_result必须='denied'
-- 这通过应用层强制，DDL层不直接限制(因为系统可能需要创建vault记录)
