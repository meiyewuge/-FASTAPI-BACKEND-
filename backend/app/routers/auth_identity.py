"""Authoritative identity routes (Stage I1).

  POST /api/auth/wechat/login   real code2session login -> opaque 24h token
  POST /api/auth/logout         revoke current session
  GET  /api/auth/me             current identity (bound member/role/store or unbound)

All responses use the {code, msg, data} envelope. No demo_user fallback.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..identity import errors, service, session_service
from ..identity.deps import require_session, _bearer_token
from ..identity.wechat import WeChatClient
from ..identity.session_service import AuthContext

router = APIRouter(prefix="/api/auth", tags=["identity"])


class WeChatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=512)


def get_wechat_client() -> WeChatClient:
    # overridable via FastAPI dependency_overrides in tests (no network)
    return WeChatClient()


@router.post("/wechat/login")
def wechat_login(req: WeChatLoginRequest, db: Session = Depends(get_db),
                 wechat: WeChatClient = Depends(get_wechat_client)):
    data = service.login_with_code(db, req.code, wechat)
    return {"code": 0, "msg": "ok", "data": data}


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = _bearer_token(request)
    session_service.revoke_session(db, token)  # idempotent; never leaks whether it existed
    return {"code": 0, "msg": "ok", "data": None}


@router.get("/me")
def me(ctx: AuthContext = Depends(require_session)):
    if not ctx.bound:
        # P1-1: unbound -> HTTP 403 (consistent with the Facade + Qoder handling),
        # carrying the fixed business message.
        raise errors.unbound()
    return {"code": 0, "msg": "ok", "data": {
        "bound": True,
        "role": ctx.role,
        # only non-sensitive authoritative identity is echoed; no openid/token
        "store_id": ctx.dl_store_id,
        "member_id": ctx.dl_member_id,
    }}
