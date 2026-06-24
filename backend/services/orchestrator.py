"""调度层（orchestrator）—— 统一控制 A/B 何时跑、是否入队、成本是否放行。

API 只与 orchestrator 对话，不直接调用引擎/服务。
职责：
  1. 投递前成本预检（熔断）
  2. 创建任务（入队思维：当前同进程异步执行，可平滑替换为 Celery/RQ）
  3. 执行时按类型分派到 a_service / b_service
"""

from __future__ import annotations

from sqlalchemy.orm import Session

import cost_engine
from intent import Intent, parse_intent
from models import Store, Task
from services import a_service, b_service, store_service
from tasks import video_task


def submit_a(db: Session, tenant_id: str, prompt: str, title: str | None = None, duration: int = 15, resolution: str = "720p") -> Task:
    cost_engine.ensure_budget(db, tenant_id, "video.generate.a", 1)
    return video_task.create_task(
        db, tenant_id, "a", {"prompt": prompt, "title": title, "duration": duration, "resolution": resolution}
    )


def submit_b(
    db: Session,
    tenant_id: str,
    source_video_id: int,
    count: int,
    prompt: str | None = None,
    strategy: str | None = "mix",
) -> Task:
    cost_engine.ensure_budget(db, tenant_id, "video.remix.b", count)
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
    )


def _build_prompt(intent: Intent, store: Store) -> str:
    desc = "".join(filter(None, [intent.theme, intent.industry])) or "宣传"
    return f"为{store.name}制作一条{desc}视频"


def plan_from_intent(db: Session, tenant_id: str, text: str) -> dict:
    """Intent Layer 入口：一句话 → 解析 → 拆单 → 创建多门店任务（仍属 1 个 tenant）。

    门店是 tenant 内 target，绝不拆 tenant。返回 plan + task 列表（由调用方分派执行）。
    """
    intent = parse_intent(text)
    count = max(1, intent.count)

    # 批量成本预检（熔断）：count 条母视频（价格计算在 cost_engine，orchestrator 只报用量）
    cost_engine.ensure_budget(db, tenant_id, "video.generate.a", count)

    stores = store_service.ensure_stores(db, tenant_id, count, intent.city, intent.industry)

    tasks: list[Task] = []
    for store in stores:
        payload = {
            "prompt": _build_prompt(intent, store),
            "store_id": store.id,
            "title": f"{store.name}·{intent.theme or '宣传'}",
        }
        tasks.append(video_task.create_task(db, tenant_id, "a", payload, store_id=store.id))

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


def run(db: Session, task: Task, payload: dict) -> dict:
    """执行期分派。由 tasks.runner 在后台调用。"""
    if task.type == "a":
        return a_service.run(db, task.tenant_id, task.id, payload)
    if task.type == "b":
        return b_service.run(db, task.tenant_id, task.id, payload)
    raise ValueError(f"未知任务类型：{task.type}")
