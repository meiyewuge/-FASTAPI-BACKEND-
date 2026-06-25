"""调度层（orchestrator）—— 统一控制 A/B 何时跑、是否入队、成本是否放行。

API 只与 orchestrator 对话，不直接调用引擎/服务。
职责：
  1. 投递前成本预检（熔断）
  2. 创建任务（入队思维：当前同进程异步执行，可平滑替换为 Celery/RQ）
  3. 执行时按类型分派到 a_service / b_service
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

import cost_engine
from config import settings
from intent import Intent, parse_intent
from models import Store, Task, Video
from services import (
    a_service, b_service, compose_service, reflow_service, store_service, subscription_service,
)
from tasks import video_task


def submit_a(db: Session, tenant_id: str, prompt: str, title: str | None = None, duration: int = 15,
             resolution: str = "720p", image_file_id: str | None = None, phone: str | None = None) -> Task:
    cost_engine.ensure_budget(db, tenant_id, "video.generate.a", 1)
    # Patch5：试用额度仅 A台扣减（B台裂变不扣）
    subscription_service.consume_trial(db, tenant_id)
    run_id = reflow_service.start_run(
        db, tenant_id, phone, "a_generate", prompt,
        input_image_count=1 if image_file_id else 0, input_text_length=len(prompt or ""),
    )
    payload = {"prompt": prompt, "title": title, "duration": duration, "resolution": resolution}
    if image_file_id:
        payload["image_file_id"] = image_file_id
    return video_task.create_task(db, tenant_id, "a", payload, run_id=run_id)


_MIN_QUALIFIED = 3       # 合格源视频最少数量（硬门槛）
_MAX_SOURCES = 5         # P1：最多取前 5 个合格源参与
_MIN_DURATION = 30       # 合格时长门槛（秒）
_THRESHOLD_MSG = "请至少上传 3 个时长 30 秒以上的视频，才能稳定裂变。"


def _qualified_sources(db: Session, tenant_id: str, source_video_ids: list[int] | None) -> list[Video]:
    """选取合格源视频：本租户 + type=mother + active + duration_seconds>=30。

    传 source_video_ids → 仅在其中筛（保持传入顺序，体现「会话源池优先」）；
    为空 → fallback 本租户最近合格源（兜底，不作主流程默认）。
    """
    base = db.query(Video).filter(
        Video.tenant_id == tenant_id,                  # 强制本租户（super_admin 也不跨租户混源）
        Video.type == "mother",
        Video.storage_status == "active",
        Video.duration_seconds.isnot(None),            # 时长未知不计入
        Video.duration_seconds >= _MIN_DURATION,
    )
    if source_video_ids:
        rows = base.filter(Video.id.in_(source_video_ids)).all()
        by_id = {v.id: v for v in rows}
        # 按传入顺序保留（前 N 个优先）
        return [by_id[i] for i in source_video_ids if i in by_id]
    return base.order_by(Video.created_at.desc()).all()


def submit_b_batch(db: Session, tenant_id: str, prompt: str | None = None,
                   source_video_ids: list[int] | None = None, auto_ratio: int = 10,
                   max_outputs: int = 50, strategy: str = "mix",
                   sources: list[dict] | None = None, phone: str | None = None) -> dict:
    """B台批量裂变（V4 P1）：会话源池优先 + 1:10，本地 ffmpeg、0 成本、不调火山。

    返回 {batch_id, source_count, total_outputs, ignored_source_video_ids, status, cost, _tasks}。
    """
    auto_ratio = max(1, min(int(auto_ratio or 10), 10))
    max_outputs = min(int(max_outputs or settings.b_batch_total_limit), settings.b_batch_total_limit)

    # 兼容 P0 旧字段 sources → source_video_ids
    if sources and not source_video_ids:
        source_video_ids = [int(s["source_video_id"]) for s in sources]

    cands = _qualified_sources(db, tenant_id, source_video_ids)
    if len(cands) < _MIN_QUALIFIED:
        raise ValueError(_THRESHOLD_MSG)

    # P1：最多取前 5 个合格源；其余记入 ignored
    used = cands[:_MAX_SOURCES]
    ignored = [v.id for v in cands[_MAX_SOURCES:]]
    used_count = len(used)

    # 1:10，封顶 max_outputs（used_count≤5 × 10 ≤ 50）
    total = min(used_count * auto_ratio, max_outputs)
    plan: list[tuple[int, int]] = []
    remaining = total
    for v in used:
        if remaining <= 0:
            break
        take = min(auto_ratio, remaining)
        plan.append((v.id, take))
        remaining -= take

    batch_id = uuid.uuid4().hex
    run_id = reflow_service.start_run(
        db, tenant_id, phone, "batch", prompt,
        input_text_length=len(prompt or ""), source_video_count=used_count,
    )
    tasks: list[Task] = []
    for vid, take in plan:
        cost_engine.ensure_budget(db, tenant_id, "video.remix.b", take)
        t = video_task.create_task(
            db, tenant_id, "b",
            {
                "source_video_id": vid,
                "count": take,
                "prompt": prompt,
                "strategy": strategy or "mix",
                "batch_id": batch_id,
            },
            batch_id=batch_id, run_id=run_id,
        )
        tasks.append(t)
    return {
        "batch_id": batch_id,
        "source_count": used_count,
        "total_outputs": total,
        "ignored_source_video_ids": ignored,
        "status": "queued",
        "cost": 0,
        "_tasks": tasks,
    }


def submit_b(
    db: Session,
    tenant_id: str,
    source_video_id: int,
    count: int,
    prompt: str | None = None,
    strategy: str | None = "mix",
    phone: str | None = None,
) -> Task:
    cost_engine.ensure_budget(db, tenant_id, "video.remix.b", count)
    run_id = reflow_service.start_run(
        db, tenant_id, phone, "b_remix", prompt,
        input_text_length=len(prompt or ""), source_video_count=1,
    )
    return video_task.create_task(
        db,
        tenant_id,
        "b",
        {
            "source_video_id": source_video_id,
            "count": count,
            "prompt": prompt,
            "strategy": strategy,
        },
        run_id=run_id,
    )


def _build_prompt(intent: Intent, store: Store) -> str:
    desc = "".join(filter(None, [intent.theme, intent.industry])) or "宣传"
    return f"为{store.name}制作一条{desc}视频"


def plan_from_intent(db: Session, tenant_id: str, text: str, phone: str | None = None) -> dict:
    """Intent Layer 入口：一句话 → 解析 → 拆单 → 创建多门店任务（仍属 1 个 tenant）。

    门店是 tenant 内 target，绝不拆 tenant。返回 plan + task 列表（由调用方分派执行）。
    """
    intent = parse_intent(text)
    count = max(1, intent.count)

    # V4 P0：防误触——一句话批量生成母视频（A台=火山花钱）上限
    if count > settings.max_a_batch:
        raise ValueError(
            f"一句话最多生成 {settings.max_a_batch} 条母视频（当前 {count}），"
            f"请拆分或改用批量裂变（B台 0 成本）"
        )

    # 批量成本预检（熔断）：count 条母视频（价格计算在 cost_engine，orchestrator 只报用量）
    cost_engine.ensure_budget(db, tenant_id, "video.generate.a", count)

    stores = store_service.ensure_stores(db, tenant_id, count, intent.city, intent.industry)

    run_id = reflow_service.start_run(
        db, tenant_id, phone, "a_generate", text, input_text_length=len(text or ""),
    )
    tasks: list[Task] = []
    for store in stores:
        payload = {
            "prompt": _build_prompt(intent, store),
            "store_id": store.id,
            "title": f"{store.name}·{intent.theme or '宣传'}",
            "duration": intent.duration or 15,        # B4：透传时长（"15秒"→duration 而非 count）
            "resolution": intent.resolution or "720p",
        }
        tasks.append(video_task.create_task(db, tenant_id, "a", payload, store_id=store.id, run_id=run_id))
        # Patch5：每条母视频（A台）扣减一次试用额度；B台裂变不扣
        subscription_service.consume_trial(db, tenant_id)

    return {
        "intent": intent.to_dict(),
        "plan": {
            "count": count,
            "target_type": intent.target_type,
            "store_ids": [s.id for s in stores],
            "task_ids": [t.id for t in tasks],
        },
        "_tasks": tasks,
    }


def submit_compose(
    db: Session, tenant_id: str, prompt: str, total_seconds: int = 30,
    resolution: str = "720p", title: str | None = None,
) -> Task:
    """B6：投递长视频「一次成型」任务（多段拼接）。"""
    from a_engine.video_composer import plan_segments

    n = len(plan_segments(total_seconds))
    cost_engine.ensure_budget(db, tenant_id, "video.generate.a", n)
    return video_task.create_task(
        db, tenant_id, "compose",
        {"prompt": prompt, "total_seconds": total_seconds, "resolution": resolution, "title": title},
    )


def run(db: Session, task: Task, payload: dict) -> dict:
    """执行期分派。由 tasks.runner 在后台调用。"""
    if task.type == "a":
        return a_service.run(db, task.tenant_id, task.id, payload)
    if task.type == "b":
        return b_service.run(db, task.tenant_id, task.id, payload)
    if task.type == "compose":
        return compose_service.run(db, task.tenant_id, task.id, payload)
    raise ValueError(f"未知任务类型：{task.type}")
