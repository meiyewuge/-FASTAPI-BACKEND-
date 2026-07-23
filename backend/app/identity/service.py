"""WeChat login orchestration: code -> openid -> AppUser -> opaque session (W3-01).

Order of enforcement (all fail-closed):
  1. per-client login rate limit           -> 429 RATE_LIMITED
  2. short-window code replay guard         -> 422 VALIDATION_ERROR
  3. real code2session (no mock fallback)   -> 422 VALIDATION_ERROR on any failure
  4. AppUser status (disabled/left)         -> 403 ROLE_FORBIDDEN, no token
  5. mint opaque 24h session (single txn)
Audit events are emitted for success and every failure class; no secret/code/
openid/token ever appears in an audit line or an error message.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from . import session_service
from . import errors
from . import audit
from .wechat import WeChatClient, WeChatError
from .ratelimit import LoginRateLimiter, CodeReplayGuard
from ..config import settings

# process-wide singletons for the real route (tests inject their own with a fake
# clock). Built lazily from the single Settings source.
_login_limiter: Optional[LoginRateLimiter] = None
_code_guard: Optional[CodeReplayGuard] = None


def get_login_limiter() -> LoginRateLimiter:
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = LoginRateLimiter(
            settings.auth_login_rate_window_seconds,
            settings.auth_login_rate_max_attempts,
        )
    return _login_limiter


def get_code_guard() -> CodeReplayGuard:
    global _code_guard
    if _code_guard is None:
        _code_guard = CodeReplayGuard(settings.auth_code_replay_window_seconds)
    return _code_guard


def _get_or_create_identity(db: Session, openid_hash: str) -> models.AppUser:
    identity = db.query(models.WechatIdentity).filter(
        models.WechatIdentity.openid_hash == openid_hash
    ).first()
    if identity is not None:
        return db.get(models.AppUser, identity.app_user_id)
    # first login: create user + identity, tolerant of a concurrent creator
    app_user = models.AppUser(status="active")
    db.add(app_user)
    db.flush()
    db.add(models.WechatIdentity(app_user_id=app_user.id, openid_hash=openid_hash))
    try:
        db.commit()
        return app_user
    except IntegrityError:
        # another concurrent first-login won the unique(openid_hash) race
        db.rollback()
        identity = db.query(models.WechatIdentity).filter(
            models.WechatIdentity.openid_hash == openid_hash
        ).first()
        if identity is None:
            raise errors.wechat_failed("登录繁忙，请重试")
        return db.get(models.AppUser, identity.app_user_id)


def login_with_code(db: Session, code: str, wechat: WeChatClient, *,
                    client_key: str = "unknown",
                    trace_id: Optional[str] = None,
                    limiter: Optional[LoginRateLimiter] = None,
                    guard: Optional[CodeReplayGuard] = None) -> dict:
    limiter = limiter or get_login_limiter()
    guard = guard or get_code_guard()

    if not limiter.allow(client_key):
        audit.audit("login_rate_limited", trace_id=trace_id, code=errors.RATE_LIMITED)
        raise errors.rate_limited()

    if not guard.check_and_remember(code):
        audit.audit("login_code_replayed", trace_id=trace_id, code=errors.VALIDATION_ERROR)
        raise errors.wechat_failed("登录凭证无效或已过期，请重试")

    try:
        openid = wechat.code2session(code)
    except WeChatError as e:
        # a dependency timeout / transport failure / missing config is a 503
        # DEPENDENCY_UNAVAILABLE (fail-closed, no mock fallback); a genuine bad or
        # expired code (rejected / no openid / malformed) is a 422 client error.
        if getattr(e, "reason", None) in ("transport_error", "not_configured"):
            audit.audit("login_dependency_unavailable", trace_id=trace_id,
                        code=errors.DEPENDENCY_UNAVAILABLE)
            raise errors.dependency_unavailable()
        audit.audit("login_wechat_failed", trace_id=trace_id, code=errors.VALIDATION_ERROR)
        raise errors.wechat_failed()

    openid_hash = session_service.hash_openid(openid)
    app_user = _get_or_create_identity(db, openid_hash)

    # a disabled/left user is never issued a token
    if app_user.status != "active":
        audit.audit("login_account_disabled", trace_id=trace_id,
                    app_user_id=app_user.id, code=errors.ROLE_FORBIDDEN)
        raise errors.account_disabled()

    binding = db.query(models.StoreMemberBinding).filter(
        models.StoreMemberBinding.app_user_id == app_user.id
    ).first()
    bound = binding is not None and binding.status == "active"

    raw_token, expires_at = session_service.mint_session(db, app_user, binding)
    audit.audit("login_success", trace_id=trace_id, app_user_id=app_user.id,
                code="OK", bound=bound)
    return {
        "token": raw_token,
        "expires_at": expires_at.isoformat(),
        "expires_in": session_service.SESSION_TTL_SECONDS,
        "bound": bound,
    }
