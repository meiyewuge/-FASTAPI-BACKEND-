"""Daily Loop Facade (Stage I1) — the ONLY Daily Loop surface exposed to the
mini-program.

  GET /api/daily-loop/v1/tasks?date=YYYY-MM-DD
  GET /api/daily-loop/v1/appointments?date=YYYY-MM-DD

Rules:
  - {code,msg,data}; success data={items:[...]}; <=100 items/day; stable sort.
  - identity comes from the authoritative session ONLY; client must NOT send
    store_id/member_id/role -> 400.
  - invalid date -> 400.
  - resolves identity, signs via backend.app.adapters.daily_loop_adapter, forwards
    to the Daily Loop internal API; unavailable -> structured 503 (no internal detail).
  - main backend holds only DM_ADAPTER_SHARED_SECRET; adapter default OFF.
  - no recovery/vault/holdings surface added.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request

from ..config import settings
from ..identity import errors
from ..identity.deps import require_session
from ..identity.session_service import AuthContext
from ..identity.daily_loop_client import DailyLoopClient, DailyLoopUnavailable
from ..adapters import daily_loop_adapter

router = APIRouter(prefix="/api/daily-loop/v1", tags=["daily-loop-facade"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORBIDDEN_CLIENT_PARAMS = ("store_id", "member_id", "role", "auth_user_id", "target_store_id")
MAX_ITEMS = 100


def get_daily_loop_client() -> DailyLoopClient:
    # overridable in tests; base URL from the single Settings source (R1c)
    return DailyLoopClient(base_url=settings.dm_daily_loop_base_url)


def _build_adapter() -> "daily_loop_adapter.DailyLoopAdapter":
    # R1c: adapter configured entirely from the single Settings source (enable flag,
    # shared secret, main-backend root isolation) — no second os.environ path. Built
    # inside the request so a config/isolation failure becomes a structured 503
    # (fail-closed) instead of a dependency-resolution crash.
    return daily_loop_adapter.DailyLoopAdapter(
        shared_secret=settings.dm_adapter_shared_secret,
        main_backend=settings.dm_main_backend,
        enabled=settings.dm_daily_loop_adapter_enabled,
    )


def _valid_date(date: str) -> bool:
    if not date or not _DATE_RE.match(date):
        return False
    try:
        y, m, d = (int(x) for x in date.split("-"))
        import datetime as _dt
        _dt.date(y, m, d)
        return True
    except (ValueError, TypeError):
        return False


def _reject_forbidden_params(request: Request) -> None:
    for p in _FORBIDDEN_CLIENT_PARAMS:
        if p in request.query_params:
            raise errors.bad_request("请求不允许携带身份参数", code=40001)


def _require_bound(ctx: AuthContext) -> None:
    if not ctx.bound:
        raise errors.unbound()


def _fetch(request: Request, ctx: AuthContext, upstream_path: str, date: str,
           client: DailyLoopClient) -> dict:
    _reject_forbidden_params(request)
    if not _valid_date(date):
        raise errors.bad_request("日期格式错误，应为 YYYY-MM-DD", code=40002)
    _require_bound(ctx)
    query = {"date": date} if upstream_path.endswith("appointments") else {"task_date": date}
    # adapter disabled (feature flag OFF, from Settings) -> dependency not ready
    # (checked WITHOUT a broad except so programming errors are never swallowed).
    if not settings.dm_daily_loop_adapter_enabled:
        raise errors.dependency_unavailable()
    # R1c: build the real adapter from Settings; missing/short shared secret or a
    # main-backend key-root isolation violation fails closed as a structured 503
    # (no secret value or internal detail leaked).
    try:
        adapter = _build_adapter()
    except (daily_loop_adapter.AdapterConfigError,
            daily_loop_adapter.MainBackendKeyIsolationError):
        raise errors.dependency_unavailable()
    try:
        headers = adapter.build_headers(
            "GET", upstream_path, b"",
            auth_user_id=ctx.dl_auth_user_id, target_store_id=ctx.dl_store_id, query=query)
        body = client.get(upstream_path, params=query, headers=headers)
    except DailyLoopUnavailable:
        raise errors.dependency_unavailable()
    # R1-5: fail closed on a broken upstream protocol; never disguise it as empty data.
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise errors.dependency_unavailable()
    items = body["items"]
    if any(not isinstance(it, dict) for it in items):
        raise errors.dependency_unavailable()
    items = items[:MAX_ITEMS]
    return {"code": 0, "msg": "ok", "data": {"items": items}}


@router.get("/tasks")
def tasks(request: Request, date: str = "",
          ctx: AuthContext = Depends(require_session),
          client: DailyLoopClient = Depends(get_daily_loop_client)):
    return _fetch(request, ctx, "/v1/dl/internal/tasks", date, client)


@router.get("/appointments")
def appointments(request: Request, date: str = "",
                 ctx: AuthContext = Depends(require_session),
                 client: DailyLoopClient = Depends(get_daily_loop_client)):
    return _fetch(request, ctx, "/v1/dl/internal/appointments", date, client)
