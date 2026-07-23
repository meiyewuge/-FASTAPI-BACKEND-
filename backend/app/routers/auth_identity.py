"""Authoritative employee-identity routes (DSM W3-01).

  POST /api/auth/wechat/login   real code2session login -> opaque 24h token (PUBLIC)
  GET  /api/auth/me             current identity (bound member/role/store or unbound)
  POST /api/auth/logout         revoke current session (idempotent)

All responses use the W1 unified envelope {code, message, trace_id, data}; success
code is "OK" and data is always present (object or null). No demo_user fallback;
the client never supplies store_id / role — they are resolved from the session and
the authoritative binding only. The external store id is an opaque
``store_<opaque12>`` and the external member id is ``mbr_<opaque12>``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..identity import service, session_service, envelope
from ..identity.deps import require_session, _bearer_token
from ..identity.wechat import WeChatClient
from ..identity.session_service import AuthContext

router = APIRouter(prefix="/api/auth", tags=["identity"])


class WeChatLoginRequest(BaseModel):
    # actor is PUBLIC; store / role are NEVER accepted from the client body.
    code: str = Field(..., min_length=1, max_length=512)


def get_wechat_client() -> WeChatClient:
    # overridable via FastAPI dependency_overrides in tests (no network)
    return WeChatClient()


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/wechat/login", operation_id="w3_01_auth_wechat_login")
def wechat_login(req: WeChatLoginRequest, request: Request,
                 db: Session = Depends(get_db),
                 wechat: WeChatClient = Depends(get_wechat_client)):
    trace_id = envelope.trace_id_of(request)
    data = service.login_with_code(
        db, req.code, wechat,
        client_key=_client_key(request), trace_id=trace_id,
    )
    return envelope.ok(data, request)


@router.get("/me", operation_id="w3_01_auth_me")
def me(request: Request, ctx: AuthContext = Depends(require_session)):
    if not ctx.bound:
        # valid session but no active store binding -> 200 + bound=false (order §4.2.3).
        return envelope.ok(
            {"bound": False, "role": None, "store_id": None, "member_id": None},
            request,
        )
    return envelope.ok({
        "bound": True,
        "role": ctx.role,
        "store_id": ctx.store_public_id,     # opaque store_<opaque12>
        "member_id": ctx.member_public_id,   # opaque mbr_<opaque12>
    }, request)


@router.post("/logout", operation_id="w3_01_auth_logout")
def logout(request: Request, db: Session = Depends(get_db)):
    token = _bearer_token(request)
    # idempotent; never leaks whether the session existed
    session_service.revoke_session(db, token)
    return envelope.ok(None, request)
