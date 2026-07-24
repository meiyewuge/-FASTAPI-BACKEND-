"""FastAPI dependencies for the authoritative identity chain (W3-01).

require_session extracts a Bearer token and resolves it to an AuthContext. There
is NO demo_user / bare-header / mock fallback: a missing or malformed Authorization
header is 401 SESSION_INVALID. Legacy mock/demo tokens are explicitly rejected so
the old mock login can never authenticate on the new routes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from . import errors
from . import session_service
from .session_service import AuthContext


def _bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    tok = parts[1].strip()
    # explicitly reject legacy mock/demo tokens on the new routes
    if not tok or tok == "demo_user" or tok.startswith("token_mock_openid") or tok.startswith("token_"):
        return None
    return tok


def require_session(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    """Resolve an authoritative session or raise errors.ApiError (401/403)."""
    token = _bearer_token(request)
    if token is None:
        raise errors.session_invalid()
    return session_service.resolve_session(db, token)
