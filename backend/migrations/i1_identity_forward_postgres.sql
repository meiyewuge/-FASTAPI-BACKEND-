-- Stage I1-R1a forward migration (PostgreSQL dialect).
-- Real identity PKs, BIGINT FKs, BOOLEAN DEFAULT FALSE, TIMESTAMP now() defaults,
-- CHECK constraints, unique wechat->user, status_epoch triggers, machine schema
-- version. Idempotent (IF NOT EXISTS). Matches the ORM.
-- NOTE: not executed against a real PostgreSQL in this environment
-- (POSTGRES_RUNTIME_NOT_EXECUTED); reviewed DDL for Stage D3. Apply via psql/alembic
-- so the $$ trigger-function body is handled correctly.

CREATE TABLE IF NOT EXISTS dl_app_user (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status        VARCHAR(16) NOT NULL DEFAULT 'active'
                  CHECK (status in ('active','disabled','left')),
    status_epoch  INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dl_wechat_identity (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    app_user_id   BIGINT NOT NULL REFERENCES dl_app_user(id),
    openid_hash   VARCHAR(64) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_wechat_openid_hash ON dl_wechat_identity(openid_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_wechat_app_user ON dl_wechat_identity(app_user_id);

CREATE TABLE IF NOT EXISTS dl_store_member_binding (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    app_user_id       BIGINT NOT NULL REFERENCES dl_app_user(id),
    dl_auth_user_id   VARCHAR(128) NOT NULL,
    dl_store_id       VARCHAR(128) NOT NULL,
    dl_member_id      VARCHAR(128) NOT NULL,
    role              VARCHAR(16) NOT NULL CHECK (role in ('owner','manager','staff')),
    status            VARCHAR(16) NOT NULL DEFAULT 'active'
                      CHECK (status in ('active','disabled','left')),
    status_epoch      INTEGER NOT NULL DEFAULT 0,
    identity_version  INTEGER NOT NULL DEFAULT 1,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_binding_app_user ON dl_store_member_binding(app_user_id);
CREATE INDEX IF NOT EXISTS ix_dl_binding_store ON dl_store_member_binding(dl_store_id);

CREATE TABLE IF NOT EXISTS dl_auth_session (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_hash             VARCHAR(64) NOT NULL,
    app_user_id            BIGINT NOT NULL REFERENCES dl_app_user(id),
    snap_auth_user_id      VARCHAR(128),
    snap_store_id          VARCHAR(128),
    snap_member_id         VARCHAR(128),
    snap_role              VARCHAR(16),
    snap_bound             BOOLEAN NOT NULL DEFAULT FALSE,
    snap_user_epoch        INTEGER NOT NULL DEFAULT 0,
    snap_binding_epoch     INTEGER,
    issued_at              TIMESTAMP NOT NULL DEFAULT now(),
    expires_at             TIMESTAMP NOT NULL,
    revoked                BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_session_token_hash ON dl_auth_session(token_hash);
CREATE INDEX IF NOT EXISTS ix_dl_session_user ON dl_auth_session(app_user_id);

-- status_epoch bump function + triggers (covers out-of-band SQL updates)
CREATE OR REPLACE FUNCTION dl_bump_status_epoch() RETURNS trigger AS $$
BEGIN
    IF NEW.status <> OLD.status THEN
        NEW.status_epoch := OLD.status_epoch + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_dl_app_user_status_epoch ON dl_app_user;
CREATE TRIGGER trg_dl_app_user_status_epoch
BEFORE UPDATE OF status ON dl_app_user
FOR EACH ROW EXECUTE FUNCTION dl_bump_status_epoch();

DROP TRIGGER IF EXISTS trg_dl_binding_status_epoch ON dl_store_member_binding;
CREATE TRIGGER trg_dl_binding_status_epoch
BEFORE UPDATE OF status ON dl_store_member_binding
FOR EACH ROW EXECUTE FUNCTION dl_bump_status_epoch();

CREATE TABLE IF NOT EXISTS dl_identity_schema_meta (version VARCHAR(32) PRIMARY KEY);
INSERT INTO dl_identity_schema_meta (version) VALUES ('i1-r1a') ON CONFLICT DO NOTHING;
