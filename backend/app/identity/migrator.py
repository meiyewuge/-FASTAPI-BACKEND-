"""Controlled identity migration state machine (W3-01 / R2 P0-1, P0-2).

A single-version state machine drives the identity schema so the version table
holds EXACTLY one row at all times:

  * blank DB              -> fresh install of dsm-w3-01-r1
  * ['dsm-w3-01'] (R0)    -> preflight conflict check, then an ATOMIC upgrade that
                            adds the two authoritative-binding unique indexes AND
                            replaces the version row with dsm-w3-01-r1 in one unit
  * ['dsm-w3-01-r1']      -> idempotent no-op (schema already current)
  * unknown / multiple    -> fail closed BEFORE any DDL (MigrationError)

The upgrade preflight rejects duplicate authoritative bindings (same
dl_store_id+dl_member_id or dl_store_id+dl_auth_user_id) with a controlled
MigrationConflict that never echoes a raw internal id. The upgrade runs in ONE
explicit transaction on both dialects: if the second index or the version
replacement fails, the first index is rolled back too (no half-migration).

The app never runs this automatically; apply via the migrator/CI step.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, List, Optional, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import SCHEMA_VERSION  # 'dsm-w3-01-r1'

_MIG_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"
_PREFIX = "w3_01_identity"
_PREV_VERSION = "dsm-w3-01"          # the R0 machine schema version
_CURRENT_VERSION = SCHEMA_VERSION    # 'dsm-w3-01-r1'
_META_TABLE = "dl_identity_schema_meta"


class MigrationError(RuntimeError):
    """Unrecognized / ambiguous schema version: fail closed, no DDL."""


class MigrationConflict(RuntimeError):
    """An authoritative-binding uniqueness conflict blocks the R0->R1 upgrade.
    Carries only a safe summary (conflict class + counts), never a raw internal id."""


def _dialect(engine: Engine) -> str:
    name = engine.dialect.name
    if name == "sqlite":
        return "sqlite"
    if name in ("postgresql", "postgres"):
        return "postgres"
    raise RuntimeError(f"unsupported dialect for identity migration: {name}")


def forward_sql_path(engine: Engine) -> Path:
    return _MIG_DIR / f"{_PREFIX}_forward_{_dialect(engine)}.sql"


def rollback_sql_path(engine: Engine) -> Path:
    return _MIG_DIR / f"{_PREFIX}_rollback_{_dialect(engine)}.sql"


def _has_meta_table(engine: Engine) -> bool:
    from sqlalchemy import inspect
    return _META_TABLE in set(inspect(engine).get_table_names())


def current_versions(engine: Engine) -> List[str]:
    """Version rows currently in the meta table ([] if the table is absent)."""
    if not _has_meta_table(engine):
        return []
    with engine.connect() as conn:
        # constant, no interpolation (identifiers are fixed literals)
        return [r[0] for r in conn.execute(text("SELECT version FROM dl_identity_schema_meta"))]


def _exec_fresh_script(engine: Engine, sql: str) -> None:
    """Run the full fresh-install DDL (contains triggers / $$ bodies)."""
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        if engine.dialect.name == "sqlite":
            cur.executescript(sql)  # trigger bodies need executescript
        else:
            cur.execute(sql)        # psycopg2 keeps $$ bodies intact in one call
        raw.commit()
    finally:
        raw.close()


# All DDL/DML below are FIXED literal statements (no interpolation, no user input):
# the identifiers and version strings are compile-time constants.
_PREFLIGHT_SQL = (
    "SELECT COUNT(*) FROM (SELECT 1 FROM dl_store_member_binding "
    "GROUP BY dl_store_id, dl_member_id HAVING COUNT(*) > 1)",
    "SELECT COUNT(*) FROM (SELECT 1 FROM dl_store_member_binding "
    "GROUP BY dl_store_id, dl_auth_user_id HAVING COUNT(*) > 1)",
)
_CREATE_INDEX_1 = ("CREATE UNIQUE INDEX uq_dl_binding_store_member "
                   "ON dl_store_member_binding(dl_store_id, dl_member_id)")
_CREATE_INDEX_2 = ("CREATE UNIQUE INDEX uq_dl_binding_store_authuser "
                   "ON dl_store_member_binding(dl_store_id, dl_auth_user_id)")
_DELETE_PREV_SQL = "DELETE FROM dl_identity_schema_meta WHERE version = 'dsm-w3-01'"
_INSERT_CURRENT_SQL = "INSERT INTO dl_identity_schema_meta (version) VALUES ('dsm-w3-01-r1')"


def _upgrade_r0_to_current(engine: Engine,
                           _fault_after_first_index: Optional[Callable[[], None]] = None) -> None:
    """Atomic R0->R1 upgrade: preflight + 2 unique indexes + version replacement in
    ONE transaction, on either dialect. `_fault_after_first_index` is a TEST-ONLY
    seam proving a failure after the first index rolls the first index back too.

    SQLite needs manual transaction control because pysqlite auto-commits DDL under
    its default isolation handling; PostgreSQL DDL is already transactional.
    """
    if engine.dialect.name == "sqlite":
        _upgrade_sqlite(engine, _fault_after_first_index)
    else:
        _upgrade_transactional(engine, _fault_after_first_index)


def _upgrade_sqlite(engine: Engine, fault: Optional[Callable[[], None]]) -> None:
    raw = engine.raw_connection()
    try:
        dbapi = cast(sqlite3.Connection, raw.dbapi_connection)  # SQLAlchemy 2.0
        prev_iso = dbapi.isolation_level
        dbapi.isolation_level = None  # disable pysqlite implicit DDL commits
        cur = dbapi.cursor()
        try:
            cur.execute("BEGIN")
            for sql in _PREFLIGHT_SQL:
                n = cur.execute(sql).fetchone()[0]
                if n and int(n) > 0:
                    raise MigrationConflict(_conflict_msg(int(n)))
            cur.execute(_CREATE_INDEX_1)
            if fault is not None:
                fault()
            cur.execute(_CREATE_INDEX_2)
            cur.execute(_DELETE_PREV_SQL)
            cur.execute(_INSERT_CURRENT_SQL)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            dbapi.isolation_level = prev_iso
    finally:
        raw.close()


def _upgrade_transactional(engine: Engine, fault: Optional[Callable[[], None]]) -> None:
    with engine.begin() as conn:
        for sql in _PREFLIGHT_SQL:
            n = conn.exec_driver_sql(sql).scalar()
            if n and int(n) > 0:
                raise MigrationConflict(_conflict_msg(int(n)))
        conn.exec_driver_sql(_CREATE_INDEX_1)
        if fault is not None:
            fault()
        conn.exec_driver_sql(_CREATE_INDEX_2)
        conn.exec_driver_sql(_DELETE_PREV_SQL)
        conn.exec_driver_sql(_INSERT_CURRENT_SQL)


def _conflict_msg(groups: int) -> str:
    # safe summary only: number of colliding groups; never a raw internal id.
    return (f"authoritative binding conflict: {groups} duplicate authoritative "
            f"binding group(s); resolve duplicates before upgrading "
            f"(no internal ids disclosed)")


def apply_forward(engine: Engine,
                  _fault_after_first_index: Optional[Callable[[], None]] = None) -> None:
    """Idempotent, single-version forward migration (state machine above)."""
    versions = current_versions(engine)
    vset = set(versions)

    if len(versions) > 1:
        raise MigrationError(
            f"identity schema version ambiguous: expected one row, found {sorted(versions)}")

    if not versions:
        # blank DB (or meta table absent) -> fresh install of the current schema
        _exec_fresh_script(engine, forward_sql_path(engine).read_text())
        return

    if vset == {_CURRENT_VERSION}:
        # already current -> idempotent no-op (re-running fresh DDL would be safe too,
        # but a strict no-op avoids any accidental second version row).
        return

    if vset == {_PREV_VERSION}:
        _upgrade_r0_to_current(engine, _fault_after_first_index=_fault_after_first_index)
        return

    # any other single value is an unrecognized version -> fail closed, no DDL
    raise MigrationError(
        f"unrecognized identity schema version: {versions[0]!r} "
        f"(expected {_PREV_VERSION!r} or {_CURRENT_VERSION!r})")


def _exec_rollback_script(engine: Engine, sql: str) -> None:
    _exec_fresh_script(engine, sql)


def apply_rollback(engine: Engine) -> None:
    # dialect-aware: SQLite drops tables (triggers auto-drop); PostgreSQL also drops
    # the status-epoch function. PG-only SQL is never fed to SQLite.
    _exec_rollback_script(engine, rollback_sql_path(engine).read_text())
