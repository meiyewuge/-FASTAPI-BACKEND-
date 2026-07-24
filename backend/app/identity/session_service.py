"""Opaque 24h session lifecycle + authoritative identity resolution (W3-01).

Token is a 256-bit random secret; only sha256(token) is stored.

Guarantees:
  - AppUser.status is enforced at mint and on every resolve (disabled/left reject).
  - The session stores a SNAPSHOT of the identity at mint time; resolve compares it
    field-by-field with constant-time equality against the LIVE binding. Any drift
    (role/store/member/auth_user/status), even without a hand-bumped
    identity_version, invalidates the old token. identity_version stays as
    defense-in-depth.
  - openid is pseudonymized with HMAC-SHA256 under an INDEPENDENT key
    (DM_OPENID_HMAC_KEY) when configured; otherwise a salted sha256 (dev only).
  - The externally exposed store id is the opaque registry public_id and the member
    id is the opaque binding.member_public_id — never a raw internal id.
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
from . import store_registry
from . import audit
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
    Salted sha256 is pseudonymization only and is NOT claimed to resist a full DB
    compromise — the HMAC key is required in staging/prod (readiness enforces it)."""
    key = settings.dm_openid_hmac_key or ""
    if key and len(key) >= 32:
        return hmac.new(key.encode("utf-8"), openid.encode("utf-8"), hashlib.sha256).hexdigest()
    return hashlib.sha256(_OPENID_SALT + openid.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    app_user_id: int
    bound: bool
    role: Optional[str] = None
    store_public_id: Optional[str] = None   # opaque store_<opaque12>
    member_public_id: Optional[str] = None  # opaque mbr_<opaque12>


def _ce(a: Optional[str], b: Optional[str]) -> bool:
    """constant-time equality tolerant of None."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def mint_session(db: Session, app_user: models.AppUser,
                 binding: Optional[models.StoreMemberBinding], *,
                 commit: bool = True, trace_id: Optional[str] = None) -> tuple[str, datetime]:
    """Add an opaque session row for the user. With commit=False the row is only
    flushed and the CALLER owns the single atomic commit (P0-3 login). `binding`
    must already be active if provided (login rejects disabled/left before minting,
    P0-1); an inactive binding here is treated as unbound defensively."""
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
        # pin status epochs so ANY status change (active->disabled->active)
        # permanently invalidates this token, incl. out-of-band DB updates.
        snap_user_epoch=(app_user.status_epoch or 0),
        snap_binding_epoch=(binding.status_epoch if bound else None),
        expires_at=expires_at,
        revoked=False,
    )
    db.add(sess)
    if commit:
        db.commit()
    else:
        db.flush()
    audit.audit("session_issued", trace_id=trace_id, app_user_id=app_user.id,
                code="OK", bound=bound)
    return raw_token, expires_at


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_session(db: Session, token: Optional[str]) -> AuthContext:
    """Resolve a bearer token to an authoritative AuthContext, or raise ApiError.
      401 SESSION_INVALID  missing/unknown/revoked/identity-drift/epoch-drift;
      401 SESSION_EXPIRED  past TTL;
      403 ROLE_FORBIDDEN   AppUser disabled/left, or binding disabled/left.
    An authenticated but UNBOUND user resolves successfully with bound=False (the
    caller decides whether the specific endpoint requires a binding).
    """
    if not token or not isinstance(token, str):
        raise errors.session_invalid()
    sess = db.query(models.AuthSession).filter(
        models.AuthSession.token_hash == hash_token(token)
    ).first()
    if sess is None or sess.revoked:
        raise errors.session_invalid()
    if _as_aware(sess.expires_at) <= _now():
        raise errors.session_expired()

    # AppUser status enforced on every resolve
    app_user = db.get(models.AppUser, sess.app_user_id)
    if app_user is None or app_user.status != "active":
        raise errors.account_disabled()
    # any AppUser status change since mint (even active->disabled->active)
    # permanently invalidates this token via the status_epoch pinned at mint.
    if (app_user.status_epoch or 0) != (sess.snap_user_epoch or 0):
        raise errors.session_invalid("身份状态已变更，请重新登录")

    binding = db.query(models.StoreMemberBinding).filter(
        models.StoreMemberBinding.app_user_id == sess.app_user_id
    ).first()

    if sess.snap_bound:
        # session was minted bound -> live binding MUST still match the snapshot
        if binding is None:
            raise errors.session_invalid("身份已变更，请重新登录")
        drift = (
            not _ce(binding.dl_auth_user_id, sess.snap_auth_user_id)
            or not _ce(binding.dl_store_id, sess.snap_store_id)
            or not _ce(binding.dl_member_id, sess.snap_member_id)
            or not _ce(binding.role, sess.snap_role)
        )
        if drift:
            raise errors.session_invalid("身份已变更，请重新登录")
        if (binding.status_epoch or 0) != (sess.snap_binding_epoch or 0):
            raise errors.session_invalid("身份状态已变更，请重新登录")
        if binding.status != "active":
            raise errors.account_disabled()
        store_public_id = store_registry.resolve_public_store_id(db, binding.dl_store_id)
        if not store_public_id:
            # bound to a store missing from the authoritative registry: fail closed
            # rather than leak a raw internal id. No internal detail in the message.
            raise errors.internal_error()
        return AuthContext(
            app_user_id=sess.app_user_id, bound=True, role=binding.role,
            store_public_id=store_public_id, member_public_id=binding.member_public_id,
        )

    # session minted unbound. If a binding appeared later, require re-login so the
    # session carries a real snapshot (never inherit a new binding on an old token).
    if binding is not None:
        raise errors.session_invalid("身份已变更，请重新登录")
    return AuthContext(app_user_id=sess.app_user_id, bound=False)


def revoke_session(db: Session, token: Optional[str], *,
                   trace_id: Optional[str] = None) -> None:
    """Revoke the session for a bearer token. Idempotent: revoking an already-revoked
    or unknown/absent token is a silent success (never leaks whether it existed).
    A `session_revoked` audit is emitted ONLY on a first real revocation, so the
    audit trail does not reveal whether a token existed."""
    if not token:
        return
    sess = db.query(models.AuthSession).filter(
        models.AuthSession.token_hash == hash_token(token)
    ).first()
    if sess is not None and not sess.revoked:
        sess.revoked = True
        db.commit()
        audit.audit("session_revoked", trace_id=trace_id, app_user_id=sess.app_user_id,
                    code="OK")
