"""Authoritative employee-identity models (DSM W3-01).

Chain: WeChat openid -> AppUser (internal) -> StoreMemberBinding (authoritative
member/role/store) ; AuthSession is an opaque 24h server session.

W3-01 additions over the referenced Stage-I1 identity:
  - StoreRegistry (DR-01=A): a single authoritative store registry that maps the
    three internal store identifiers (main ORM int Store.id, v0.1.3 string
    store_id, and binding.dl_store_id) to ONE external opaque ``store_<opaque12>``.
    Each internal identifier is UNIQUE, so a given internal store maps to exactly
    one external id. Only the opaque public_id is ever exposed by the API.
  - StoreMemberBinding.member_public_id: an opaque ``mbr_<opaque12>`` external
    member id (never the raw v0.1.3 free-text dl_member_id) so /me exposes no raw
    internal identifier (W1 rule: no int PK, no free-text/name/phone as an ID).
  - StoreMemberBinding has a UNIQUE(app_user_id): a user has AT MOST ONE active
    binding, so there is no ambiguous multi-binding / "switch store" case in this
    round (order §4.2.6).

status_epoch (on AppUser and StoreMemberBinding) is bumped by a DB trigger on ANY
status change (incl. out-of-band SQL). A session pins both epochs at mint; resolve
rejects on mismatch, so active->disabled->active permanently invalidates old
tokens. dl_identity_schema_meta carries a machine schema version verified by
readiness. Identity models live on a SEPARATE declarative base so the legacy
Base.metadata.create_all() never creates them; they come only from the migration.
"""
from __future__ import annotations

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Integer,
                        String, UniqueConstraint, Index, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..config import settings

_PK = Integer if settings.database_url.startswith("sqlite") else __import__(
    "sqlalchemy").BigInteger
_FK = _PK

ROLE_VALUES = ("owner", "manager", "staff")
STATUS_VALUES = ("active", "disabled", "left")
SCHEMA_VERSION = "dsm-w3-01-r1"


class IdentityBase(DeclarativeBase):
    """Separate metadata: NOT created by the legacy Base.metadata.create_all()."""
    pass


class SchemaMeta(IdentityBase):
    __tablename__ = "dl_identity_schema_meta"
    version: Mapped[str] = mapped_column(String(32), primary_key=True)


class StoreRegistry(IdentityBase):
    """Authoritative store registry (DR-01=A). Maps the three internal store id
    spaces to one external opaque id. Internal ids are UNIQUE where present."""
    __tablename__ = "dl_store_registry"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_dl_store_public_id"),
        UniqueConstraint("dl_store_id", name="uq_dl_store_dl_store_id"),
        UniqueConstraint("main_store_id", name="uq_dl_store_main_store_id"),
        UniqueConstraint("v013_store_id", name="uq_dl_store_v013_store_id"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    # external opaque store id: store_<opaque12>. The ONLY store id exposed by the API.
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # binding.dl_store_id space (daily-loop authority store id) — always present.
    dl_store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # main ORM Store.id (int) — optional until the main store is linked.
    main_store_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # v0.1.3 free-text store_id — optional until the v013 store is linked.
    v013_store_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at = mapped_column(DateTime, server_default=func.now())


class AppUser(IdentityBase):
    __tablename__ = "dl_app_user"
    __table_args__ = (
        CheckConstraint("status in ('active','disabled','left')", name="ck_dl_app_user_status"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    status_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    wechat = relationship("WechatIdentity", back_populates="app_user", uselist=False)
    binding = relationship("StoreMemberBinding", back_populates="app_user", uselist=False)


class WechatIdentity(IdentityBase):
    __tablename__ = "dl_wechat_identity"
    __table_args__ = (
        UniqueConstraint("openid_hash", name="uq_dl_wechat_openid_hash"),
        UniqueConstraint("app_user_id", name="uq_dl_wechat_app_user"),  # one wechat per user
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(_FK, ForeignKey("dl_app_user.id"), nullable=False)
    openid_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at = mapped_column(DateTime, server_default=func.now())

    app_user = relationship("AppUser", back_populates="wechat")


class StoreMemberBinding(IdentityBase):
    __tablename__ = "dl_store_member_binding"
    __table_args__ = (
        UniqueConstraint("app_user_id", name="uq_dl_binding_app_user"),
        UniqueConstraint("member_public_id", name="uq_dl_binding_member_public_id"),
        # P0-5: one authoritative daily-loop employee identity may belong to AT MOST
        # ONE AppUser. Both the store+member and the store+auth_user pairs are unique,
        # so the same authoritative member (or authoritative user) cannot be claimed
        # by two WeChat users. Enforced by the DB, not just caller discipline.
        UniqueConstraint("dl_store_id", "dl_member_id", name="uq_dl_binding_store_member"),
        UniqueConstraint("dl_store_id", "dl_auth_user_id", name="uq_dl_binding_store_authuser"),
        Index("ix_dl_binding_store", "dl_store_id"),
        CheckConstraint("role in ('owner','manager','staff')", name="ck_dl_binding_role"),
        CheckConstraint("status in ('active','disabled','left')", name="ck_dl_binding_status"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(_FK, ForeignKey("dl_app_user.id"), nullable=False)
    dl_auth_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dl_store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dl_member_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # external opaque member id: mbr_<opaque12>. The ONLY member id exposed by the API.
    member_public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    status_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    identity_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    app_user = relationship("AppUser", back_populates="binding")


class AuthSession(IdentityBase):
    __tablename__ = "dl_auth_session"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_dl_session_token_hash"),
        Index("ix_dl_session_user", "app_user_id"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    app_user_id: Mapped[int] = mapped_column(_FK, ForeignKey("dl_app_user.id"), nullable=False)
    snap_auth_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snap_store_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snap_member_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snap_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    snap_bound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # status epochs pinned at mint (permanent invalidation on any status change)
    snap_user_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snap_binding_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_at = mapped_column(DateTime, server_default=func.now(), nullable=False)
    expires_at = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


REQUIRED_TABLES = {
    "dl_identity_schema_meta": {"version"},
    "dl_store_registry": {"id", "public_id", "dl_store_id", "main_store_id",
                          "v013_store_id", "created_at"},
    "dl_app_user": {"id", "status", "status_epoch", "created_at", "updated_at"},
    "dl_wechat_identity": {"id", "app_user_id", "openid_hash", "created_at"},
    "dl_store_member_binding": {
        "id", "app_user_id", "dl_auth_user_id", "dl_store_id", "dl_member_id",
        "member_public_id", "role", "status", "status_epoch", "identity_version",
        "created_at", "updated_at"},
    "dl_auth_session": {
        "id", "token_hash", "app_user_id", "snap_auth_user_id", "snap_store_id",
        "snap_member_id", "snap_role", "snap_bound", "snap_user_epoch",
        "snap_binding_epoch", "issued_at", "expires_at", "revoked"},
}
REQUIRED_INDEXES = {
    "uq_dl_store_public_id", "uq_dl_store_dl_store_id", "uq_dl_store_main_store_id",
    "uq_dl_store_v013_store_id",
    "uq_dl_wechat_openid_hash", "uq_dl_wechat_app_user", "uq_dl_binding_app_user",
    "uq_dl_binding_member_public_id", "uq_dl_binding_store_member",
    "uq_dl_binding_store_authuser", "uq_dl_session_token_hash",
}
