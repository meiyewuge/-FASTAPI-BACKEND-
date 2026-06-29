"""V4 P2B-B3 API（/api/p2b-b3/*）· 三维差异评分闸门（只评分，不自动重剪/不生成/不扩批）。

独立命名空间，不污染 /api/p2b-b/*（B1）。安全闸门：
1) production/prod 环境 → 强制 403（最高优先级，即使 flag=true）。
2) ENABLE_P2B_B3_SCORE=false → 4032。
B3 全部只读既有数据 + 写 b3 派生字段，不生成新 mp4、不改 videos.status、cost=0。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from config import settings
from schemas.dto import Resp
from services import p2b_b3_service

p2b_b3_router = APIRouter(prefix="/p2b-b3")

_PROD_ENVS = {"prod", "production"}


def _is_prod() -> bool:
    return (settings.app_env or "").lower() in _PROD_ENVS


def _guard() -> None:
    """production 强制 403（最高优先级）。"""
    if _is_prod():
        raise HTTPException(status_code=403, detail="P2B-B3 评分在 production 环境被禁止")


class ScoreIn(BaseModel):
    run_id: str = Field(..., min_length=1)


class SimulateIn(BaseModel):
    production_order_id: str = Field(..., min_length=1)
    n: int = Field(50, ge=2, le=200)


@p2b_b3_router.post("/score")
def score(
    body: ScoreIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """对一个 run（batch）的 done 视频做三维评分并幂等写库（meta.b3_score + qa_json.b3_batch）。"""
    _guard()
    res = p2b_b3_service.score_run(db, user["tenant_id"], body.run_id)
    if not res["ok"]:
        return Resp(code=res["code"], message=res["reason"])
    return Resp(message="B3 评分完成（cost=0，不生成、不重剪）", data=res["data"])


@p2b_b3_router.get("/score/{run_id}")
def get_score(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """读取已写入的 b3_batch 评分结果。"""
    _guard()
    data = p2b_b3_service.get_score(db, user["tenant_id"], run_id)
    if data is None:
        return Resp(code=3001, message="run 不存在 / 未评分 / 不属于当前租户")
    return Resp(data=data)


@p2b_b3_router.get("/publish-pool/{run_id}")
def publish_pool(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """发布池读取契约：只返回 pass=true 且 recommended_action=pass_to_publish_pool 的条目。"""
    _guard()
    return Resp(data=p2b_b3_service.publish_pool(db, user["tenant_id"], run_id))


@p2b_b3_router.post("/simulate")
def simulate(
    body: SimulateIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> Resp:
    """大 N metadata-only 模拟（不渲染、不入库、不生成视频）：检测 signature 重复/档位撞车/too_similar 候选密度。"""
    _guard()
    if not settings.enable_p2b_b3_score:
        return Resp(code=4032, message="B3 评分未开启（ENABLE_P2B_B3_SCORE=false）")
    return Resp(message="大 N 模拟完成（metadata-only，cost=0）",
                data=p2b_b3_service.simulate(body.production_order_id, body.n))
