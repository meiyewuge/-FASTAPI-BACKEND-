"""Authoritative store registry resolution (DR-01=A).

The registry maps the three internal store id spaces (main ORM int Store.id,
v0.1.3 string store_id, binding.dl_store_id) to ONE external opaque
``store_<opaque12>``. The API only ever exposes the opaque public_id — never a
raw int / v013 free-text id / dl_store_id.

`register_store` is the single writer used by identity provisioning and by tests
to seed a binding's store; it is idempotent on any of the three internal ids and
never mints a second external id for the same internal store.
"""
from __future__ import annotations

import secrets
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def _new_public_store_id() -> str:
    # store_ + 12 hex chars (48 bits of entropy); opaque and non-enumerable.
    return "store_" + secrets.token_hex(6)


def new_member_public_id() -> str:
    return "mbr_" + secrets.token_hex(6)


def resolve_public_store_id(db: Session, dl_store_id: str) -> Optional[str]:
    """Map an internal binding.dl_store_id to its external opaque store id, or None
    when the store is not registered (caller decides the fail-closed response)."""
    row = db.query(models.StoreRegistry).filter(
        models.StoreRegistry.dl_store_id == dl_store_id
    ).first()
    return row.public_id if row else None


def register_store(db: Session, dl_store_id: str,
                   main_store_id: Optional[int] = None,
                   v013_store_id: Optional[str] = None) -> models.StoreRegistry:
    """Idempotently ensure a registry row for a store, keyed by dl_store_id. If the
    row exists, backfill any newly supplied internal ids (never overwriting an
    existing distinct value); otherwise create it with a fresh opaque public id."""
    row = db.query(models.StoreRegistry).filter(
        models.StoreRegistry.dl_store_id == dl_store_id
    ).first()
    if row is None:
        row = models.StoreRegistry(
            public_id=_new_public_store_id(),
            dl_store_id=dl_store_id,
            main_store_id=main_store_id,
            v013_store_id=v013_store_id,
        )
        db.add(row)
        db.flush()
        return row
    if main_store_id is not None and row.main_store_id is None:
        row.main_store_id = main_store_id
    if v013_store_id is not None and row.v013_store_id is None:
        row.v013_store_id = v013_store_id
    db.flush()
    return row
