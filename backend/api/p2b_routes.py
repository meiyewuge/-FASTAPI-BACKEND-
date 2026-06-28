"""V4 P2B-A API（/api/p2b/*）· 主题驱动 L2 执行计划 Dry-run。

独立命名空间，不接管原 B 台接口。所有接口：
- 受 ENABLE_L2_SKILLS 开关控制（默认 false → 返回「未开启」）；
- tenant 隔离（查询带 tenant_id 过滤）；
- 只出计划，不执行：execute_allowed=false、cost=0、不调火山/remixer/ffmpeg/LLM、不写 videos。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from config import settings
from schemas.dto import Resp
from schemas.p2b_dto import ExecutionPlanConfirmIn, ExecutionPlanPreviewIn, ThemeKernelIn
from services import p2b_execution_plan_service as eps
from services import p2b_skill_catalog

p2b_router = APIRouter(prefix="/p2b")

_DISABLED = Resp(code=4031, message="P2B-A 功能未开启（ENABLE_L2_SKILLS=false）")

# production 环境硬拦截：无论 ENABLE_L2_SKILLS 是否被误配为 true，一律禁开
_PROD_ENVS = {"prod", "production"}


def _enabled() -> bool:
    """P2B-A 是否开启。V1.1 硬锁：production/prod 环境一律返回 False（禁开）。"""
    env = (settings.app_env or "").lower()
    if env in _PROD_ENVS:
        return False
    return bool(settings.enable_l2_skills)


@p2b_router.post("/theme-kernels")
def create_theme_kernel(
    body: ThemeKernelIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """从 P2A 生产单生成中心思想（ThemeKernel）。"""
    if not _enabled():
        return _DISABLED
    tk = eps.build_theme_only(db, user["tenant_id"], body.production_order_id)
    if tk is None:
        return Resp(code=3001, message="生产单不存在或不属于当前租户。")
    return Resp(message="中心思想生成成功", data=tk)


@p2b_router.post("/execution-plans/preview")
def preview_execution_plans(
    body: ExecutionPlanPreviewIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """预览 30 条执行计划（不入库，cost=0，execute_allowed=false）。"""
    if not _enabled():
        return _DISABLED
    data = eps.preview(db, user["tenant_id"], body.production_order_id, body.fission_plan_id)
    if data is None:
        return Resp(code=3001, message="生产单不存在或不属于当前租户。")
    return Resp(message="执行计划预览已生成（30条，cost=0）", data=data)


@p2b_router.post("/execution-plans")
def confirm_execution_plans(
    body: ExecutionPlanConfirmIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """确认并入库 30 条执行计划（幂等；重复提交不重复生成）。"""
    if not _enabled():
        return _DISABLED
    data = eps.confirm(db, user["tenant_id"], body.production_order_id,
                       body.fission_plan_id, user.get("phone"))
    if data is None:
        return Resp(code=3001, message="生产单不存在或不属于当前租户。")
    return Resp(message="执行计划已确认并入库（30条）", data=data)


@p2b_router.get("/execution-plans/by-production-order/{production_order_id}")
def list_by_production_order(
    production_order_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """查询某生产单下已确认的全部执行计划（tenant 隔离，仅 confirmed）。"""
    if not _enabled():
        return _DISABLED
    data = eps.list_by_production_order(db, user["tenant_id"], production_order_id)
    return Resp(message="查询成功", data=data)


@p2b_router.get("/execution-plans/{execution_plan_id}/explain")
def explain_execution_plan(
    execution_plan_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """工艺说明（全部来自持久化 JSON，不依赖临时内存）。"""
    if not _enabled():
        return _DISABLED
    data = eps.explain(db, user["tenant_id"], execution_plan_id)
    if data is None:
        return Resp(code=3001, message="执行计划不存在或不属于当前租户。")
    return Resp(message="工艺说明", data=data)


@p2b_router.get("/execution-plans/{execution_plan_id}")
def get_execution_plan(
    execution_plan_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """查看执行计划详情（含完整 variant_plan JSON）。"""
    if not _enabled():
        return _DISABLED
    data = eps.get(db, user["tenant_id"], execution_plan_id)
    if data is None:
        return Resp(code=3001, message="执行计划不存在或不属于当前租户。")
    return Resp(data=data)


@p2b_router.get("/skills")
def list_l2_skills(
    user: dict = Depends(get_current_user),
) -> Resp:
    """L2 技能列表（来自 P2B_L2_SKILL_CATALOG 常量，不读 P2A skill_registry）。"""
    if not _enabled():
        return _DISABLED
    items = p2b_skill_catalog.list_skills()
    return Resp(data={"items": items, "total": len(items)})
