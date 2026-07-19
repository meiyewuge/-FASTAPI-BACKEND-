"""Authoritative identity models (Stage I1 / R1 / R1a).

Chain: WeChat openid -> AppUser (internal) -> StoreMemberBinding (authoritative
member/role/store) ; AuthSession is an opaque 24h server session.

R1a additions:
  - status_epoch on AppUser and StoreMemberBinding: a DB trigger bumps it on ANY
    status change (incl. out-of-band SQL). The session pins both epochs at mint;
    resolve rejects (401) on mismatch, so active->disabled->active permanently
    invalidates old tokens without a manual bump (P0-3).
  - dl_identity_schema_meta: a machine schema version (i1-r1a) written atomically
    by the migration; readiness verifies the exact version (P0-2).
  - WechatIdentity.app_user_id is UNIQUE (one WeChat identity per user) and
    role/status carry CHECK constraints (P1-2).

Identity models live on a SEPARATE declarative base so legacy
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
SCHEMA_VERSION = "i1-r1a"


class IdentityBase(DeclarativeBase):
    """Separate metadata: NOT created by the legacy Base.metadata.create_all()."""
    pass


class SchemaMeta(IdentityBase):
    __tablename__ = "dl_identity_schema_meta"
    version: Mapped[str] = mapped_column(String(32), primary_key=True)


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
        Index("ix_dl_binding_store", "dl_store_id"),
        CheckConstraint("role in ('owner','manager','staff')", name="ck_dl_binding_role"),
        CheckConstraint("status in ('active','disabled','left')", name="ck_dl_binding_status"),
    )

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(_FK, ForeignKey("dl_app_user.id"), nullable=False)
    dl_auth_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dl_store_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dl_member_id: Mapped[str] = mapped_column(String(128), nullable=False)
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
    # R1a: status epochs pinned at mint (permanent invalidation on any status change)
    snap_user_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snap_binding_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_at = mapped_column(DateTime, server_default=func.now(), nullable=False)
    expires_at = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


REQUIRED_TABLES = {
    "dl_identity_schema_meta": {"version"},
    "dl_app_user": {"id", "status", "status_epoch", "created_at", "updated_at"},
    "dl_wechat_identity": {"id", "app_user_id", "openid_hash", "created_at"},
    "dl_store_member_binding": {
        "id", "app_user_id", "dl_auth_user_id", "dl_store_id", "dl_member_id",
        "role", "status", "status_epoch", "identity_version", "created_at", "updated_at"},
    "dl_auth_session": {
        "id", "token_hash", "app_user_id", "snap_auth_user_id", "snap_store_id",
        "snap_member_id", "snap_role", "snap_bound", "snap_user_epoch",
        "snap_binding_epoch", "issued_at", "expires_at", "revoked"},
}
REQUIRED_INDEXES = {
    "uq_dl_wechat_openid_hash", "uq_dl_wechat_app_user", "uq_dl_binding_app_user",
    "uq_dl_session_token_hash",
}
