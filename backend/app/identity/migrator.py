"""Controlled identity migrator (R1-1 / R1-2).

Selects the correct dialect DDL (SQLite vs PostgreSQL) instead of one
"looks-generic" SQL. Used by tests and by an operator/CI step — the app does NOT
auto-create identity tables (they live on a separate metadata; see models).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

_MIG_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def _dialect(engine: Engine) -> str:
    name = engine.dialect.name
    if name == "sqlite":
        return "sqlite"
    if name in ("postgresql", "postgres"):
        return "postgres"
    raise RuntimeError(f"unsupported dialect for identity migration: {name}")


def _exec_script(engine: Engine, sql: str) -> None:
    # execute statements one by one for portability across drivers
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        if engine.dialect.name == "sqlite":
            cur.executescript(sql)
        else:
            # psycopg2 executes a multi-statement string in one call, which keeps
            # $$-quoted trigger-function bodies intact (naive ';' splitting would
            # break them).
            cur.execute(sql)
        raw.commit()
    finally:
        raw.close()


def forward_sql_path(engine: Engine) -> Path:
    return _MIG_DIR / f"i1_identity_forward_{_dialect(engine)}.sql"


def rollback_sql_path(engine: Engine) -> Path:
    return _MIG_DIR / f"i1_identity_rollback_{_dialect(engine)}.sql"


def apply_forward(engine: Engine) -> None:
    _exec_script(engine, forward_sql_path(engine).read_text())


def apply_rollback(engine: Engine) -> None:
    # dialect-aware: SQLite drops tables (triggers auto-drop); PostgreSQL also
    # drops the status-epoch function (P1-1). PG-only SQL is never fed to SQLite.
    _exec_script(engine, rollback_sql_path(engine).read_text())
