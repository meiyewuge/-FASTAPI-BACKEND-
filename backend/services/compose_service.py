"""B6：长视频「一次成型」编排服务。

一句话 + 总时长 → 切多段(≤15s) → 逐段调 A台引擎生成 → 下载本地 → FFmpeg 拼接
→ 落本地 composed/ → 建 Video 记录（含封面 + 本地URL）→ 按段记账（按秒计费）。

只编排，不改 A/B 引擎结构；依赖 ECS 已装 ffmpeg。
"""

from __future__ import annotations

import json
import os
import tempfile

from sqlalchemy.orm import Session

import cost_engine
from a_engine.generator import generate_mother_video
from a_engine.video_composer import compose_long_video
from config import settings
from models import DirectorPlan, Task, Video
from utils import video_cover, video_storage


def run(db: Session, tenant_id: str, task_id: str, payload: dict) -> dict:
    # RISK-1 防御纵深：即便绕过路由，引擎层也拒绝未解锁的真生成
    if not settings.enable_compose:
        raise RuntimeError("生成通道维护中，暂不可用。")

    prompt = payload["prompt"]
    total_seconds = int(payload.get("total_seconds", 30))
    resolution = payload.get("resolution", "720p")
    store_id = payload.get("store_id")
    phone = payload.get("phone")

    # V4 P0-B：导演稿 → content[]（含图片 role）+ generate_audio
    director_content = None
    plan = None
    if payload.get("director_plan_id"):
        plan = db.get(DirectorPlan, payload["director_plan_id"])
        if plan and plan.seedance_text_prompt:
            director_content = json.loads(plan.image_roles_json or "[]")

    tmp = tempfile.mkdtemp()
    seg_meta: list[dict] = []

    def seg_gen(tid: str, seg_prompt: str, seconds: int, res: str) -> str:
        # 同一套参考图锚定所有段：每段 content = 段文案 text + 导演稿图片 roles
        content = None
        if director_content:
            content = [{"type": "text", "text": seg_prompt}] + [
                {"type": "image_url", "image_url": {"url": r["url"]}, "role": r["role"]}
                for r in director_content if r.get("url")
            ]
        data = generate_mother_video(
            tid, seg_prompt, duration=seconds, resolution=res,
            content=content, generate_audio=settings.compose_generate_audio,
            ratio=settings.compose_ratio,
        )
        # BUG-2：拿到 provider_job_id 立即预扣费 + 持久化（恢复防重复 submit）
        job_id = data["meta"].get("provider_task_id")
        if job_id:
            t = db.get(Task, task_id)
            if t is not None and not t.provider_job_id:
                t.provider_job_id = job_id
            cost_engine.cost_ledger.precharge(
                db, tenant_id, task_id, job_id, "compose", seconds, res,
                model=settings.volc_model, user_phone=phone,
            )
            db.flush()
        path = os.path.join(tmp, f"seg_{len(seg_meta)}.mp4")
        video_storage.download_to(data["url"], path)
        seg_meta.append({
            "units": data.get("units", 1),
            "duration": seconds,
            "provider": data["meta"].get("served_by") or data["meta"].get("provider") or "",
        })
        return path

    out_dir = os.path.join(settings.storage_dir, "composed")
    result = compose_long_video(tenant_id, prompt, total_seconds, resolution, seg_gen, out_dir)

    video = Video(
        tenant_id=tenant_id,
        store_id=store_id,
        type="mother",
        title=payload.get("title") or prompt[:50],
        meta=json.dumps({"composed": True, **result}, ensure_ascii=False),
    )
    db.add(video)
    db.flush()

    # 重命名成片为 {id}.mp4 并设本地URL/封面
    final_path = os.path.join(out_dir, f"{video.id}.mp4")
    os.replace(result["output_path"], final_path)
    video.duration_seconds = float(result.get("total_seconds") or total_seconds)  # V4 P1
    video.local_url = video_storage.local_url(video.id, "composed")
    video.download_url = video.local_url
    video.cover_url = video_cover.extract_cover(video.id, final_path, "composed")

    # 按段记账（每段按真实秒数 + 分辨率，per-second 计费）
    for sm in seg_meta:
        cost_engine.record(
            db, tenant_id, "video.generate.a", sm["units"], task_id,
            provider=sm["provider"], store_id=store_id,
            duration=sm["duration"], resolution=resolution,
        )
    db.commit()

    return {
        "video_id": video.id,
        "type": "mother_composed",
        "segments": result["segments"],
        "segment_seconds": result["segment_seconds"],
        "total_seconds": result["total_seconds"],
        "download_url": video.download_url,
        "cover_url": video.cover_url,
    }
