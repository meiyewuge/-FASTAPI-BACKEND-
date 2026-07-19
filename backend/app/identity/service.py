"""WeChat login orchestration: code -> openid -> AppUser -> opaque session (R1).

R1: enforces AppUser.status at login (disabled/left -> 403, no token); handles the
concurrent first-login race on the unique openid hash (rollback + re-query).
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from . import session_service
from .wechat import WeChatClient, WeChatError
from . import errors


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
            # extremely unlikely; surface as a generic retryable failure
            raise errors.wechat_failed("登录繁忙，请重试", code=40011)
        return db.get(models.AppUser, identity.app_user_id)


def login_with_code(db: Session, code: str, wechat: WeChatClient) -> dict:
    try:
        openid = wechat.code2session(code)
    except WeChatError:
        raise errors.wechat_failed()

    openid_hash = session_service.hash_openid(openid)
    app_user = _get_or_create_identity(db, openid_hash)

    # R1-3: a disabled/left user is never issued a token
    if app_user.status != "active":
        raise errors.forbidden("账号已停用，请联系门店管理员", code=40303)

    binding = db.query(models.StoreMemberBinding).filter(
        models.StoreMemberBinding.app_user_id == app_user.id
    ).first()

    raw_token, expires_at = session_service.mint_session(db, app_user, binding)
    return {
        "token": raw_token,
        "expires_at": expires_at.isoformat(),
        "expires_in": session_service.SESSION_TTL_SECONDS,
        "bound": binding is not None and binding.status == "active",
    }
