"""Opaque 24h session lifecycle + authoritative identity resolution (R1).

Token is a 256-bit random secret; only sha256(token) is stored.

R1 hard guarantees:
  - AppUser.status is enforced at mint and on every resolve (disabled/left -> reject).
  - The session stores a SNAPSHOT of the identity at mint time; resolve compares it
    field-by-field with constant-time equality against the LIVE binding. Any drift
    (role/store/member/auth_user/status), even without a hand-bumped
    identity_version, invalidates the old token (401). identity_version stays as
    defense-in-depth.
  - openid is pseudonymized with HMAC-SHA256 under an INDEPENDENT key
    (DM_OPENID_HMAC_KEY) when configured; otherwise a salted sha256 (dev only).
    The independent key is never the wechat secret / S2S / Recovery / Vault root.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from . import errors
from ..config import settings

SESSION_TTL_SECONDS = 24 * 3600  # fixed 24h, no refresh
_OPENID_SALT = b"dm_daily_loop_openid_v1"  # dev-only salt when no HMAC key configured


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_openid(openid: str) -> str:
    """Pseudonymize the openid. With an independent DM_OPENID_HMAC_KEY (>=32 chars)
    this is HMAC-SHA256 (keyed pseudonym); otherwise a salted sha256 for dev.
    NOTE: salted sha256 is pseudonymization only and is NOT claimed to resist a
    full DB compromise — use the HMAC key in staging/prod."""
    key = settings.dm_openid_hmac_key or ""
    if key and len(key) >= 32:
        return hmac.new(key.encode("utf-8"), openid.encode("utf-8"), hashlib.sha256).hexdigest()
    return hashlib.sha256(_OPENID_SALT + openid.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    app_user_id: int
    bound: bool
    dl_auth_user_id: Optional[str] = None
    dl_store_id: Optional[str] = None
    dl_member_id: Optional[str] = None
    role: Optional[str] = None


def _ce(a: Optional[str], b: Optional[str]) -> bool:
    """constant-time equality tolerant of None."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def mint_session(db: Session, app_user: models.AppUser,
                 binding: Optional[models.StoreMemberBinding]) -> tuple[str, datetime]:
    raw_token = secrets.token_hex(32)  # 256-bit
    expires_at = _now() + timedelta(seconds=SESSION_TTL_SECONDS)
    bound = binding is not None and binding.status == "active"
    sess = models.AuthSession(
        token_hash=hash_token(raw_token),
        app_user_id=app_user.id,
        snap_bound=bound,
        snap_auth_user_id=(binding.dl_auth_user_id if bound else None),
        snap_store_id=(binding.dl_store_id if bound else None),
        snap_member_id=(binding.dl_member_id if bound else None),
        snap_role=(binding.role if bound else None),
        # R1a: pin status epochs so ANY status change (active->disabled->active)
        # permanently invalidates this token, incl. out-of-band DB updates.
        snap_user_epoch=(app_user.status_epoch or 0),
        snap_binding_epoch=(binding.status_epoch if bound else None),
        expires_at=expires_at,
        revoked=False,
    )
    db.add(sess)
    db.commit()
    return raw_token, expires_at


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_session(db: Session, token: Optional[str]) -> AuthContext:
    """Resolve a bearer token to an authoritative AuthContext, or raise ApiError.
      401 missing/unknown/expired/revoked/identity-drift;
      403 AppUser disabled/left, binding disabled/left, or unbound-at-use.
    """
    if not token or not isinstance(token, str):
        raise errors.unauthenticated()
    sess = db.query(models.AuthSession).filter(
        models.AuthSession.token_hash == hash_token(token)
    ).first()
    if sess is None or sess.revoked:
        raise errors.unauthenticated()
    if _as_aware(sess.expires_at) <= _now():
        raise errors.unauthenticated("登录已过期")

    # R1-3: AppUser status enforced on every resolve
    app_user = db.get(models.AppUser, sess.app_user_id)
    if app_user is None or app_user.status != "active":
        raise errors.forbidden("账号已停用，请重新登录或联系门店管理员", code=40303)
    # R1a P0-3: any AppUser status change since mint (even active->disabled->active)
    # permanently invalidates this token via the status_epoch pinned at mint.
    if (app_user.status_epoch or 0) != (sess.snap_user_epoch or 0):
        raise errors.unauthenticated("身份状态已变更，请重新登录")

    binding = db.query(models.StoreMemberBinding).filter(
        models.StoreMemberBinding.app_user_id == sess.app_user_id
    ).first()

    if sess.snap_bound:
        # session was minted bound -> live binding MUST still match the snapshot
        if binding is None:
            raise errors.unauthenticated("身份已变更，请重新登录")
        # R1-4: field-by-field snapshot vs live comparison (no reliance on version)
        drift = (
            not _ce(binding.dl_auth_user_id, sess.snap_auth_user_id)
            or not _ce(binding.dl_store_id, sess.snap_store_id)
            or not _ce(binding.dl_member_id, sess.snap_member_id)
            or not _ce(binding.role, sess.snap_role)
        )
        if drift:
            raise errors.unauthenticated("身份已变更，请重新登录")
        # R1a P0-3: binding status epoch drift (active->disabled->active) invalidates
        if (binding.status_epoch or 0) != (sess.snap_binding_epoch or 0):
            raise errors.unauthenticated("身份状态已变更，请重新登录")
        if binding.status != "active":
            raise errors.forbidden("账号已停用，请联系门店管理员", code=40302)
        return AuthContext(
            app_user_id=sess.app_user_id, bound=True,
            dl_auth_user_id=binding.dl_auth_user_id, dl_store_id=binding.dl_store_id,
            dl_member_id=binding.dl_member_id, role=binding.role,
        )

    # session minted unbound. If a binding appeared later, require re-login so the
    # session carries a real snapshot (never inherit a new binding on an old token).
    if binding is not None:
        raise errors.unauthenticated("身份已变更，请重新登录")
    return AuthContext(app_user_id=sess.app_user_id, bound=False)


def revoke_session(db: Session, token: Optional[str]) -> None:
    if not token:
        return
    sess = db.query(models.AuthSession).filter(
        models.AuthSession.token_hash == hash_token(token)
    ).first()
    if sess is not None and not sess.revoked:
        sess.revoked = True
        db.commit()
