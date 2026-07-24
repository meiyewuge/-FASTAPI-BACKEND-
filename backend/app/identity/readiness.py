"""Identity readiness + config gates (W3-01 §6/§8).

check_ready: when IDENTITY_I1_ENABLED, verify the identity + store-registry tables
plus key columns/indexes AND the exact machine schema version exist (created by
the reviewed migration). Missing/old/unknown version fails closed.

check_identity_config: when enabled, verify WeChat + HMAC configuration is
complete and the HMAC key is independent of every other process secret. Both fail
closed at startup — never a half-usable state. Error messages carry key names /
codes only, never secret values.
"""
from __future__ import annotations

import os

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .models import REQUIRED_TABLES, REQUIRED_INDEXES, SCHEMA_VERSION


class IdentityNotReady(RuntimeError):
    """Raised at startup when IDENTITY_I1_ENABLED but the schema is not migrated."""


class IdentityConfigError(RuntimeError):
    """Raised at startup when IDENTITY_I1_ENABLED but config is incomplete/unsafe.
    Message contains key names / error codes only — never secret values."""


def check_ready(engine: Engine) -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    missing_tables = [t for t in REQUIRED_TABLES if t not in existing_tables]
    if missing_tables:
        raise IdentityNotReady(f"identity migration incomplete: missing tables {sorted(missing_tables)}")
    for tbl, cols in REQUIRED_TABLES.items():
        have = {c["name"] for c in insp.get_columns(tbl)}
        missing_cols = cols - have
        if missing_cols:
            raise IdentityNotReady(f"identity migration incomplete: {tbl} missing columns {sorted(missing_cols)}")
    have_idx = set()
    for tbl in REQUIRED_TABLES:
        for idx in insp.get_indexes(tbl):
            if idx.get("name"):
                have_idx.add(idx["name"])
        for uc in insp.get_unique_constraints(tbl):
            if uc.get("name"):
                have_idx.add(uc["name"])
    missing_idx = REQUIRED_INDEXES - have_idx
    if missing_idx:
        raise IdentityNotReady(f"identity migration incomplete: missing indexes {sorted(missing_idx)}")
    with engine.connect() as conn:
        rows = [r[0] for r in conn.execute(text("SELECT version FROM dl_identity_schema_meta"))]
    if SCHEMA_VERSION not in rows:
        raise IdentityNotReady(
            f"identity schema version mismatch: expected {SCHEMA_VERSION!r}, found {sorted(rows)!r}")
    if len(rows) != 1:
        raise IdentityNotReady("identity schema version ambiguous: expected exactly one version row")


# daily-loop secret roots the main backend must never hold and the openid HMAC key
# must never equal. These are NOT Settings-managed (they belong to Daily Loop); the
# process environment is consulted only for this independence check.
_ENV_ONLY_ROOTS = (
    "DM_CALLER_SIGNING_KEY", "DM_PLATFORM_RECOVERY_SIGNING_KEY",
    "DM_PLATFORM_RECOVERY_SECRET", "DM_VAULT_MASTER_KEY",
)


def check_identity_config(settings, env=None) -> None:
    """Fail closed unless the identity config (single Settings source) is complete,
    the main-backend flag is set, and the HMAC key is independent of every other
    secret. WeChat / HMAC values come ONLY from Settings (no Settings vs os.environ
    drift); the env is consulted only for the daily-loop roots the main backend must
    not carry. No secret VALUES ever appear in errors. Only used when enabled."""
    env = env if env is not None else os.environ
    missing = [name for name, val in (("WECHAT_APP_ID", settings.wechat_app_id),
                                      ("WECHAT_APP_SECRET", settings.wechat_app_secret)) if not val]
    if missing:
        raise IdentityConfigError(f"identity config incomplete: missing {sorted(missing)}")
    if not settings.dm_main_backend:
        raise IdentityConfigError("identity config invalid: DM_MAIN_BACKEND must be true")
    hmac_key = settings.dm_openid_hmac_key or ""
    if len(hmac_key) < 32:
        raise IdentityConfigError("identity config invalid: DM_OPENID_HMAC_KEY missing or shorter than 32")
    for name, val in (("WECHAT_APP_SECRET", settings.wechat_app_secret),
                      ("DM_ADAPTER_SHARED_SECRET", settings.dm_adapter_shared_secret)):
        if val and val == hmac_key:
            raise IdentityConfigError(f"identity config invalid: DM_OPENID_HMAC_KEY must not equal {name}")
    for name in _ENV_ONLY_ROOTS:
        other = env.get(name)
        if other and other == hmac_key:
            raise IdentityConfigError(f"identity config invalid: DM_OPENID_HMAC_KEY must not equal {name}")
    # R2 P1-4: AUTH_TRUSTED_PROXIES must be valid exact IPs / CIDRs, else fail closed.
    from . import proxy
    try:
        proxy.parse_trusted_proxies(settings.auth_trusted_proxies)
    except ValueError:
        raise IdentityConfigError(
            "identity config invalid: AUTH_TRUSTED_PROXIES must be exact IPs or CIDRs")
