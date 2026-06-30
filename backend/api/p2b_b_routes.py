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


def _guard_real_execution(db: Session, tenant_id: str, max_items: int) -> Resp | None:
    """真实执行闸门。

    production：默认 403；仅当 B2.6 灰度窄门**全部条件满足**才放行（白名单 + 配额 + B3 必开 + max_items≤gray_max）。
    staging：沿用 ENABLE_P2B_REAL_EXECUTION + b1_max_items。
    """
    if _is_prod():
        # B2.6 生产灰度窄门：不满足任一条件 → 维持 403
        gray_ok = (settings.enable_p2b_production_gray
                   and tenant_id in (settings.p2b_gray_tenant_allowlist or [])
                   and settings.enable_p2b_b3_score
                   and max_items <= settings.p2b_gray_max_items)
        if not gray_ok:
            raise HTTPException(status_code=403,
                                detail="P2B-B 真实执行在 production 未满足灰度窄门（gray/白名单/B3/max_items）")
        if p2b_b_service.today_run_count(db, tenant_id) >= settings.p2b_gray_daily_run_quota:
            raise HTTPException(status_code=403,
                                detail=f"P2B-B production 灰度今日配额已用尽（{settings.p2b_gray_daily_run_quota}）")
        return None        # 灰度放行（窄门即授权，不再依赖 ENABLE_P2B_REAL_EXECUTION）
    # staging 路径（不变）
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
    """真实执行小批量（staging：flag 双闸门；production：B2.6 灰度窄门）。含 B2.6 去重拦截。"""
    blocked = _guard_real_execution(db, user["tenant_id"], body.max_items)
    if blocked is not None:
        return blocked
    res = p2b_b_service.execute_run(
        db, user["tenant_id"], user.get("phone"), body.production_order_id,
        body.execution_plan_ids, body.source_video_id, body.max_items,
        (settings.app_env or "").lower(), force=bool(getattr(body, "force", False)),
    )
    if res.get("duplicate_run"):
        return Resp(message="命中窗口内同参 run，返回已有 run（未创建新 run）", data=res["data"])
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
