"""API 统一出口 /api/*。

约束：api 层只与 orchestrator / service 对话，不直接 import a_engine / b_engine。
所有请求经 get_tenant_id 拿到租户并据此隔离。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

import analytics
import cost_engine
from api.deps import get_db, get_tenant_id, require_admin
from config import settings
from b_engine.strategies import STRATEGIES
from cost_engine import QuotaExceeded, get_or_create_tenant
from intent import parse_intent
from models import Store, Video
from schemas.dto import (
    AGenerateIn, BGenerateIn, ComposeIn, ExportIn, IntentIn,
    InviteGenIn, InviteRevokeIn, LoginIn, Resp,
)
from services import (
    export_service, invite_service, orchestrator, store_service,
    subscription_service, upload_service,
)
from tasks import video_task
from utils.upload_util import UploadError
from tasks.runner import execute_task, retry_task
from utils import jwt_util, url_refresh

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


# ---------------- 鉴权（Patch4：邀约码 + JWT）----------------
@api_router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> Resp:
    """手机号 + 邀约码登录。无邀约码 / 邀约码无效 → 拒绝；成功签发 JWT。"""
    result = invite_service.validate_and_consume(db, body.invite_code, body.phone)
    if not result["ok"]:
        return Resp(code=result["code"], message=result["message"])
    tenant_id = result["tenant_id"]
    get_or_create_tenant(db, tenant_id)
    db.commit()
    token = jwt_util.encode(
        {"tenant_id": tenant_id, "phone": body.phone},
        settings.jwt_secret,
        ttl_seconds=settings.jwt_ttl_seconds,
    )
    return Resp(data={"token": token, "tenant_id": tenant_id})


# ---------------- 管理员：邀约码（最小版，X-Admin-Key 守卫）----------------
@api_router.post("/admin/invite/generate")
def admin_invite_generate(
    body: InviteGenIn,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
) -> Resp:
    items = invite_service.generate(
        db, body.count, body.tenant_id, body.max_uses, body.note
    )
    return Resp(data={"items": items, "count": len(items)})


@api_router.get("/admin/invite/list")
def admin_invite_list(
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
) -> Resp:
    items = invite_service.list_codes(db)
    return Resp(data={"items": items, "total": len(items)})


@api_router.post("/admin/invite/revoke")
def admin_invite_revoke(
    body: InviteRevokeIn,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
) -> Resp:
    ok = invite_service.revoke(db, body.code)
    if not ok:
        return Resp(code=3001, message="邀约码不存在")
    return Resp(data={"code": body.code, "active": False})


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
        return Resp(code=4029, message=str(e))
    for t in result.pop("_tasks"):
        bg.add_task(execute_task, t.id)
    return Resp(data=result)


@api_router.post("/compose")
def compose(
    body: ComposeIn,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """B6：长视频一次成型——切多段→生成→FFmpeg拼接→输出完整成片（异步，返回 task_id）。"""
    try:
        task = orchestrator.submit_compose(
            db, tenant_id, body.prompt, body.total_seconds, body.resolution, body.title
        )
    except QuotaExceeded as e:
        return Resp(code=4029, message=str(e))
    bg.add_task(execute_task, task.id)
    return Resp(data={"task_id": task.id})


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
        task = orchestrator.submit_a(db, tenant_id, body.prompt, body.title, duration=body.duration, resolution=body.resolution)
    except QuotaExceeded as e:
        return Resp(code=4029, message=str(e))
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
            db, tenant_id, body.source_video_id, body.count, body.prompt, body.strategy
        )
    except QuotaExceeded as e:
        return Resp(code=4029, message=str(e))
    bg.add_task(execute_task, task.id)
    return Resp(data={"task_id": task.id})


@api_router.get("/b/strategies")
def b_strategies() -> Resp:
    """B台可选内容策略（供前端选择）。"""
    items = [
        {"key": k, "label": v["label"], "goal": v["goal"], "cta": v["cta"]}
        for k, v in STRATEGIES.items()
    ]
    return Resp(data={"items": items})


# ---------------- 任务 ----------------
@api_router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    t = video_task.get_task(db, tenant_id, task_id)
    if t is None:
        return Resp(code=3001, message="任务不存在")
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
        return Resp(code=3001, message="任务不存在")
    if t.status != "failed":
        return Resp(code=2001, message="仅失败任务可重试")
    bg.add_task(retry_task, task_id)
    return Resp(data={"task_id": task_id, "status": "pending"})


# ---------------- 历史视频（筛选）----------------
@api_router.get("/videos")
def list_videos(
    type: str = "mother",
    page: int = 1,
    page_size: int = 20,
    strategy: str | None = None,
    store_id: int | None = None,
    source_video_id: int | None = None,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    vtype = "viral" if type in ("viral", "裂变") else "mother"
    q = db.query(Video).filter(Video.tenant_id == tenant_id, Video.type == vtype)
    if strategy:
        q = q.filter(Video.strategy == strategy)
    if store_id is not None:
        q = q.filter(Video.store_id == store_id)
    if source_video_id is not None:
        q = q.filter(Video.source_video_id == source_video_id)
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
            "strategy": v.strategy,
            "store_id": v.store_id,
            "source_video_id": v.source_video_id,
            "download_url": v.download_url,
            "share_url": v.share_url,
            "cover_url": v.cover_url,
        }
        for v in rows
    ]
    return Resp(data={"items": items, "total": total})


@api_router.get("/videos/{video_id}/url")
def get_video_url(
    video_id: int,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """B1：取可用播放/下载 URL；火山签名过期则自动刷新后返回。"""
    v = db.query(Video).filter(Video.id == video_id, Video.tenant_id == tenant_id).first()
    if v is None:
        return Resp(code=3001, message="视频不存在")
    url = url_refresh.refresh_video_url(db, v)
    return Resp(data={"video_id": v.id, "download_url": url, "share_url": v.share_url})


# ---------------- 上传（Patch2）----------------
@api_router.post("/upload")
def upload(
    type: str = Form(...),
    file: UploadFile | None = File(None),
    content: str | None = Form(None),
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """上传 image(jpg/png/webp≤10MB) / video(mp4/mov/avi≤500MB) / text(脚本文案)。"""
    try:
        if type == "text":
            data = (content or "").encode("utf-8")
            fname = "text.txt"
        else:
            if file is None:
                return Resp(code=2001, message="缺少文件")
            data = file.file.read()
            fname = file.filename
        result = upload_service.handle_upload(db, tenant_id, type, fname, data)
    except UploadError as e:
        return Resp(code=2001, message=str(e))
    return Resp(data=result)


# ---------------- 导出（筛选→清单，不分发）----------------
@api_router.post("/export")
def export(
    body: ExportIn,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
):
    """按 ids 或筛选条件导出视频清单（json/csv）。仅产清单，不对接外部平台。"""
    videos = export_service.select_videos(
        db, tenant_id, body.video_ids, body.type, body.strategy,
        body.store_id, body.source_video_id,
    )
    items = export_service.build_manifest(db, tenant_id, videos)
    if body.format == "csv":
        return PlainTextResponse(
            export_service.manifest_to_csv(items),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=videos_export.csv"},
        )
    return Resp(data={"count": len(items), "items": items})


@api_router.post("/export/videos")
def export_videos(
    body: ExportIn,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Resp:
    """视频导出（方案B）：返回选中视频的 mp4 下载 URL 列表（前端逐条下载）。
    保留 /api/export 的 CSV/JSON 元数据导出不变；ZIP 打包留待下一阶段。"""
    videos = export_service.select_videos(
        db, tenant_id, body.video_ids, body.type, body.strategy,
        body.store_id, body.source_video_id,
    )
    items = [
        {
            "video_id": v.id,
            "type": v.type,
            "title": v.title,
            "download_url": v.download_url,
            "cover_url": v.cover_url,
        }
        for v in videos
    ]
    return Resp(data={"count": len(items), "videos": items})


# ---------------- 订阅/试用（Patch5，暂不接支付）----------------
@api_router.get("/subscription/status")
def subscription_status(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    """返回订阅状态、试用余量、配额余量。试用仅 A台扣减，B台不扣。"""
    return Resp(data=subscription_service.get_status(db, tenant_id))


# ---------------- 成本 ----------------
@api_router.get("/cost/summary")
def cost_summary(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    return Resp(data=cost_engine.summary(db, tenant_id))


@api_router.get("/cost/by-store")
def cost_by_store(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    """门店级成本报表（真实台账：每门店产了多少视频、花了多少）。"""
    return Resp(data={"items": cost_engine.by_store(db, tenant_id)})


@api_router.get("/cost/by-provider")
def cost_by_provider(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    return Resp(data={"items": cost_engine.by_provider(db, tenant_id)})


# ---------------- 业务指标层（成本侧推导，无收入/ROI 假设）----------------
@api_router.get("/metrics/overview")
def metrics_overview(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    """内容效率总览：产出/成本/每元产出/裂变倍率。"""
    return Resp(data=analytics.overview(db, tenant_id))


@api_router.get("/metrics/by-store")
def metrics_by_store(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    """门店产能与成本效率。"""
    return Resp(data={"items": analytics.by_store(db, tenant_id)})


@api_router.get("/metrics/by-strategy")
def metrics_by_strategy(
    db: Session = Depends(get_db), tenant_id: str = Depends(get_tenant_id)
) -> Resp:
    """各内容策略产出条数与成本占比。"""
    return Resp(data={"items": analytics.by_strategy(db, tenant_id)})


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
