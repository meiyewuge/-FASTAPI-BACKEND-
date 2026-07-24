"""WeChat login orchestration: code -> openid -> AppUser -> opaque session (W3-01).

Order of enforcement (all fail-closed):
  1. per-client login rate limit           -> 429 RATE_LIMITED
  2. short-window code replay guard         -> 422 VALIDATION_ERROR
  3. real code2session (no mock fallback)   -> 422 VALIDATION_ERROR / 503 on timeout
  4. AppUser status (disabled/left)         -> 403 ROLE_FORBIDDEN, no token (P0-1)
  5. binding status (disabled/left)         -> 403 ROLE_FORBIDDEN, no token (P0-1)
  6. mint opaque 24h session

R1 P0-3: for a first-time user the AppUser + WechatIdentity + AuthSession are
written in ONE atomic transaction (a single commit); if the session insert fails,
none of the three survive. A concurrent first-login race on the unique openid hash
is retried against the now-existing identity, never leaving orphans and never
leaking database internals.

R1 P0-1: a login is only `200 + bound=true/false` for a truly unbound user or an
active binding; a binding that is disabled/left is a fail-closed 403 with NO
session issued (dl_auth_session row count is unchanged on rejection).

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


def _find_user_by_openid(db: Session, openid_hash: str) -> Optional[models.AppUser]:
    identity = db.query(models.WechatIdentity).filter(
        models.WechatIdentity.openid_hash == openid_hash
    ).first()
    if identity is None:
        return None
    return db.get(models.AppUser, identity.app_user_id)


def _issue_for_user(db: Session, app_user: models.AppUser, *,
                    trace_id: Optional[str]) -> dict:
    """Status-machine + session mint for an already-persisted user, committed in the
    caller's single transaction. Raises (rolled back by caller) on a disabled user
    or a disabled/left binding — with NO session row added."""
    if app_user.status != "active":
        audit.audit("binding_rejected", trace_id=trace_id, app_user_id=app_user.id,
                    code=errors.ROLE_FORBIDDEN, reason="user_status")
        raise errors.account_disabled()

    binding = db.query(models.StoreMemberBinding).filter(
        models.StoreMemberBinding.app_user_id == app_user.id
    ).first()
    # P0-1: distinguish "no binding" (unbound login OK) from "inactive binding"
    # (fail-closed, no session).
    if binding is not None and binding.status != "active":
        audit.audit("binding_rejected", trace_id=trace_id, app_user_id=app_user.id,
                    code=errors.ROLE_FORBIDDEN, reason="binding_status")
        raise errors.account_disabled()

    active_binding = binding if (binding is not None and binding.status == "active") else None
    raw_token, expires_at = session_service.mint_session(
        db, app_user, active_binding, commit=False, trace_id=trace_id)
    return {
        "token": raw_token,
        "expires_at": expires_at.isoformat(),
        "expires_in": session_service.SESSION_TTL_SECONDS,
        "bound": active_binding is not None,
    }


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
        if getattr(e, "reason", None) in ("transport_error", "not_configured"):
            audit.audit("login_dependency_unavailable", trace_id=trace_id,
                        code=errors.DEPENDENCY_UNAVAILABLE)
            raise errors.dependency_unavailable()
        audit.audit("login_wechat_failed", trace_id=trace_id, code=errors.VALIDATION_ERROR)
        raise errors.wechat_failed()

    openid_hash = session_service.hash_openid(openid)

    # Single atomic transaction with a bounded retry for the concurrent-first-login
    # race on the unique openid hash. Any error rolls back the whole unit (no
    # orphan AppUser/WechatIdentity/AuthSession, P0-3).
    for attempt in range(2):
        try:
            app_user = _find_user_by_openid(db, openid_hash)
            if app_user is None:
                app_user = models.AppUser(status="active")
                db.add(app_user)
                db.flush()
                db.add(models.WechatIdentity(app_user_id=app_user.id, openid_hash=openid_hash))
                db.flush()  # surfaces the unique(openid_hash) race here, still same txn
            data = _issue_for_user(db, app_user, trace_id=trace_id)
            db.commit()
            audit.audit("login_success", trace_id=trace_id, app_user_id=app_user.id,
                        code="OK", bound=data["bound"])
            return data
        except errors.ApiError:
            db.rollback()  # fail-closed rejection: no residue
            raise
        except IntegrityError:
            db.rollback()
            if attempt == 0:
                continue  # concurrent creator won; retry against the existing identity
            audit.audit("login_conflict", trace_id=trace_id, code=errors.INTERNAL_ERROR)
            raise errors.wechat_failed("登录繁忙，请重试")
        except Exception:
            # any unexpected error rolls back the whole unit (no orphan
            # AppUser/WechatIdentity/AuthSession) and propagates to the 500 handler.
            db.rollback()
            raise
    # unreachable, but keeps type-checkers happy
    raise errors.wechat_failed("登录繁忙，请重试")
