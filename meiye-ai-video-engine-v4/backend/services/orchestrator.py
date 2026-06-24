"""调度层（orchestrator）—— 统一控制 A/B 何时跑、是否入队、成本是否放行。

API 只与 orchestrator 对话，不直接调用引擎/服务。
职责：
  1. 投递前成本预检（熔断）
  2. 创建任务（入队思维：当前同进程异步执行，可平滑替换为 Celery/RQ）
  3. 执行时按类型分派到 a_service / b_service
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from config import settings
from models import Task
from services import a_service, b_service, cost_service
from tasks import video_task


def submit_a(db: Session, tenant_id: str, prompt: str, title: str | None = None) -> Task:
    cost_service.ensure_budget(db, tenant_id, settings.cost_per_mother)
    return video_task.create_task(
        db, tenant_id, "a", {"prompt": prompt, "title": title}
    )


def submit_b(
    db: Session, tenant_id: str, source_video_id: int, count: int, prompt: str | None = None
) -> Task:
    estimated = count * settings.cost_per_clip
    cost_service.ensure_budget(db, tenant_id, estimated)
    return video_task.create_task(
        db,
        tenant_id,
        "b",
        {"source_video_id": source_video_id, "count": count, "prompt": prompt},
    )


def run(db: Session, task: Task, payload: dict) -> dict:
    """执行期分派。由 tasks.runner 在后台调用。"""
    if task.type == "a":
        return a_service.run(db, task.tenant_id, task.id, payload)
    if task.type == "b":
        return b_service.run(db, task.tenant_id, task.id, payload)
    raise ValueError(f"未知任务类型：{task.type}")
