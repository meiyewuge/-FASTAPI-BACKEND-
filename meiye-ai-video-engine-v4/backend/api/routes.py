"""API 统一出口 /api/*。

约束：api 层只与 orchestrator / service 对话，不直接 import a_engine / b_engine。
所有请求经 get_tenant_id 拿到租户并据此隔离。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from api.deps import get_db, get_tenant_id
from config import settings
from intent import parse_intent
from models import Store, Video
from schemas.dto import AGenerateIn, BGenerateIn, IntentIn, LoginIn, Resp
from services import cost_service, orchestrator, store_service
from services.cost_service import QuotaExceeded
from tasks import video_task
from tasks.runner import execute_task, retry_task

api_router = APIRouter()


def _task_brief(t) -> dict:
    return {
        "task_id": t.id,
        "type": t.type,
        "status": t.status,
        "progress": t.progress,
        "retry_count": t.retry_count,
        "result": json.loads(t.result) if t.result else None,
        "error": t.error or None,
    }


# ---------------- 鉴权 ----------------
@api_router.post("/auth/login")
def login(body: LoginIn, tenant_id: str = Depends(get_tenant_id)) -> Resp:
    """手机号 / token 登录，绑定 tenant_id（占位鉴权）。"""
    return Resp(data={"token": f"tk_{tenant_id}", "tenant_id": tenant_id})


# ---------------- Intent Layer（业务理解层）----------------
@api_router.post("/intent/plan")
def intent_plan(body: IntentIn) -> Resp:
    """仅解析：一句话 → 结构化 Intent（不落库、不执行）。"""
    return Resp(data=parse_intent(body.text).to_dict())


@api_router.post("/generate")
def generate(
    body: IntentIn,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """统一入口：一句话 → 解析 → 多门店拆单 → 自动创建并分派任务（仍属 1 个 tenant）。"""
    try:
        result = orchestrator.plan_from_intent(db, tenant_id, body.text)
    except QuotaExceeded as e:
        return Resp(code=4029, msg=str(e))
    for t in result.pop("_tasks"):
        bg.add_task(execute_task, t.id)
    return Resp(data=result)


@api_router.get("/stores")
def list_stores(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    rows = store_service.list_stores(db, tenant_id)
    items = [
        {"store_id": s.id, "name": s.name, "city": s.city, "industry": s.industry}
        for s in rows
    ]
    return Resp(data={"items": items, "total": len(items)})


# ---------------- A台 ----------------
@api_router.post("/a/generate")
def a_generate(
    body: AGenerateIn,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """A台：一句话 → 母视频（异步，返回 task_id）。"""
    try:
        task = orchestrator.submit_a(db, tenant_id, body.prompt, body.title)
    except QuotaExceeded as e:
        return Resp(code=4029, msg=str(e))
    bg.add_task(execute_task, task.id)
    return Resp(data={"task_id": task.id})


# ---------------- B台 ----------------
@api_router.post("/b/generate")
def b_generate(
    body: BGenerateIn,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """B台：母视频 → 批量裂变（异步，返回 task_id）。"""
    try:
        task = orchestrator.submit_b(
            db, tenant_id, body.source_video_id, body.count, body.prompt
        )
    except QuotaExceeded as e:
        return Resp(code=4029, msg=str(e))
    bg.add_task(execute_task, task.id)
    return Resp(data={"task_id": task.id})


# ---------------- 任务 ----------------
@api_router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    t = video_task.get_task(db, tenant_id, task_id)
    if t is None:
        return Resp(code=3001, msg="任务不存在")
    return Resp(data=_task_brief(t))


@api_router.get("/tasks")
def list_tasks(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    items = [_task_brief(t) for t in video_task.list_tasks(db, tenant_id)]
    return Resp(data={"items": items, "total": len(items)})


@api_router.post("/tasks/{task_id}/retry")
def retry(
    task_id: str,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    t = video_task.get_task(db, tenant_id, task_id)
    if t is None:
        return Resp(code=3001, msg="任务不存在")
    if t.status != "failed":
        return Resp(code=2001, msg="仅失败任务可重试")
    bg.add_task(retry_task, task_id)
    return Resp(data={"task_id": task_id, "status": "pending"})


# ---------------- 历史视频 ----------------
@api_router.get("/videos")
def list_videos(
    type: str = "mother",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    vtype = "viral" if type in ("viral", "裂变") else "mother"
    q = db.query(Video).filter(Video.tenant_id == tenant_id, Video.type == vtype)
    total = q.count()
    rows = (
        q.order_by(Video.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "video_id": v.id,
            "type": v.type,
            "title": v.title,
            "source_video_id": v.source_video_id,
            "download_url": v.download_url,
            "share_url": v.share_url,
        }
        for v in rows
    ]
    return Resp(data={"items": items, "total": total})


# ---------------- 成本 ----------------
@api_router.get("/cost/summary")
def cost_summary(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    return Resp(data=cost_service.summary(db, tenant_id))


# ---------------- 健康/信息 ----------------
@api_router.get("/info")
def info() -> Resp:
    return Resp(
        data={
            "service": "meiye-ai-video-engine-v4",
            "video_provider": settings.video_provider,
            "env": settings.app_env,
        }
    )
