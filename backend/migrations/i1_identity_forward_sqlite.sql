-- Stage I1-R1a forward migration (SQLite dialect).
-- Matches the ORM exactly; idempotent (IF NOT EXISTS). Adds status_epoch +
-- triggers (permanent invalidation on status change), CHECK constraints, unique
-- wechat->user mapping, and a machine schema-version row.

CREATE TABLE IF NOT EXISTS dl_app_user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    status        VARCHAR(16) NOT NULL DEFAULT 'active'
                  CHECK (status in ('active','disabled','left')),
    status_epoch  INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dl_wechat_identity (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    app_user_id   INTEGER NOT NULL REFERENCES dl_app_user(id),
    openid_hash   VARCHAR(64) NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_wechat_openid_hash ON dl_wechat_identity(openid_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_wechat_app_user ON dl_wechat_identity(app_user_id);

CREATE TABLE IF NOT EXISTS dl_store_member_binding (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    app_user_id       INTEGER NOT NULL REFERENCES dl_app_user(id),
    dl_auth_user_id   VARCHAR(128) NOT NULL,
    dl_store_id       VARCHAR(128) NOT NULL,
    dl_member_id      VARCHAR(128) NOT NULL,
    role              VARCHAR(16) NOT NULL CHECK (role in ('owner','manager','staff')),
    status            VARCHAR(16) NOT NULL DEFAULT 'active'
                      CHECK (status in ('active','disabled','left')),
    status_epoch      INTEGER NOT NULL DEFAULT 0,
    identity_version  INTEGER NOT NULL DEFAULT 1,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_binding_app_user ON dl_store_member_binding(app_user_id);
CREATE INDEX IF NOT EXISTS ix_dl_binding_store ON dl_store_member_binding(dl_store_id);

CREATE TABLE IF NOT EXISTS dl_auth_session (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash             VARCHAR(64) NOT NULL,
    app_user_id            INTEGER NOT NULL REFERENCES dl_app_user(id),
    snap_auth_user_id      VARCHAR(128),
    snap_store_id          VARCHAR(128),
    snap_member_id         VARCHAR(128),
    snap_role              VARCHAR(16),
    snap_bound             BOOLEAN NOT NULL DEFAULT 0,
    snap_user_epoch        INTEGER NOT NULL DEFAULT 0,
    snap_binding_epoch     INTEGER,
    issued_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at             TIMESTAMP NOT NULL,
    revoked                BOOLEAN NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_session_token_hash ON dl_auth_session(token_hash);
CREATE INDEX IF NOT EXISTS ix_dl_session_user ON dl_auth_session(app_user_id);

-- status_epoch triggers: bump on ANY status change, incl. out-of-band SQL.
-- "AFTER UPDATE OF status" fires only when status is assigned; updating
-- status_epoch (a different column) does not re-fire, so there is no recursion.
CREATE TRIGGER IF NOT EXISTS trg_dl_app_user_status_epoch
AFTER UPDATE OF status ON dl_app_user
FOR EACH ROW WHEN NEW.status <> OLD.status
BEGIN
    UPDATE dl_app_user SET status_epoch = OLD.status_epoch + 1 WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_dl_binding_status_epoch
AFTER UPDATE OF status ON dl_store_member_binding
FOR EACH ROW WHEN NEW.status <> OLD.status
BEGIN
    UPDATE dl_store_member_binding SET status_epoch = OLD.status_epoch + 1 WHERE id = OLD.id;
END;

-- machine schema version (P0-2)
CREATE TABLE IF NOT EXISTS dl_identity_schema_meta (version VARCHAR(32) PRIMARY KEY);
INSERT OR IGNORE INTO dl_identity_schema_meta (version) VALUES ('i1-r1a');
