"""V4 P2B-B1 API（/api/p2b-b/*）· 小批量真实执行。

独立命名空间，不污染 /api/p2b/*（P2B-A）。安全闸门优先级：
1) production/prod 环境 → **强制 403**（即使 ENABLE_P2B_REAL_EXECUTION=true）。
2) ENABLE_P2B_REAL_EXECUTION=false → runs 返回 4031。
3) max_items > 6 → 2001。
查询/预览类接口在 staging 可用；只有 runs 真实生成受 1)+2)+3) 全部约束。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from config import settings
from schemas.dto import Resp
from schemas.p2b_b_dto import RunsIn, RunsPreviewIn
from services import p2b_b_service

p2b_b_router = APIRouter(prefix="/p2b-b")

_PROD_ENVS = {"prod", "production"}


def _is_prod() -> bool:
    return (settings.app_env or "").lower() in _PROD_ENVS


def _guard_real_execution(max_items: int) -> Resp | None:
    """真实执行闸门。production 强制 403（最高优先级）。"""
    if _is_prod():
        raise HTTPException(status_code=403, detail="P2B-B1 真实执行在 production 环境被禁止")
    if not settings.enable_p2b_real_execution:
        return Resp(code=4031, message="P2B-B1 真实执行未开启（ENABLE_P2B_REAL_EXECUTION=false）")
    if max_items > settings.p2b_b1_max_items:
        return Resp(code=2001, message=f"max_items 超过上限 {settings.p2b_b1_max_items}")
    return None


@p2b_b_router.get("/eligible-plans/{production_order_id}")
def eligible_plans(
    production_order_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """列该生产单下 confirmed 的执行计划 + execute_ready。"""
    items = p2b_b_service.eligible_plans(db, user["tenant_id"], production_order_id)
    return Resp(data={"production_order_id": production_order_id, "total": len(items), "items": items})


@p2b_b_router.post("/runs/preview")
def runs_preview(
    body: RunsPreviewIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """预览本次将执行哪几条（含源校验，不生成、不入库）。"""
    res = p2b_b_service.preview_run(
        db, user["tenant_id"], body.production_order_id,
        body.execution_plan_ids, body.source_video_id, body.max_items,
    )
    if not res["ok"]:
        return Resp(code=res["code"], message=res["reason"])
    return Resp(message="预览成功（cost=0，不生成）", data=res["data"])


@p2b_b_router.post("/runs")
def runs(
    body: RunsIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """真实执行小批量（staging + flag 双闸门；production 强制 403）。"""
    blocked = _guard_real_execution(body.max_items)
    if blocked is not None:
        return blocked
    res = p2b_b_service.execute_run(
        db, user["tenant_id"], user.get("phone"), body.production_order_id,
        body.execution_plan_ids, body.source_video_id, body.max_items,
        (settings.app_env or "").lower(),
    )
    if not res["ok"]:
        return Resp(code=res["code"], message=res["reason"])
    return Resp(message="小批量真实执行完成（cost=0）", data=res["data"])


@p2b_b_router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    data = p2b_b_service.get_run(db, user["tenant_id"], run_id)
    if data is None:
        return Resp(code=3001, message="run 不存在或不属于当前租户")
    return Resp(data=data)


@p2b_b_router.get("/runs/{run_id}/items")
def list_items(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    data = p2b_b_service.list_items(db, user["tenant_id"], run_id)
    return Resp(data=data)
