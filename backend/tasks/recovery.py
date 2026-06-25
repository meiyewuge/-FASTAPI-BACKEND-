"""B3：进程内任务恢复。

当前为同进程后台执行（FastAPI BackgroundTasks）；进程重启（systemd restart）会丢失
未完成任务。启动时扫描 pending/running 任务并重新执行，避免任务永久卡死。

注：这是「至少恢复」机制；running 任务重跑可能产生重复副作用，故只对超时窗口外的
running 视为中断。真正的去重/断点续传可后续接 Celery/RQ。
"""

from __future__ import annotations

from config import settings
from db import SessionLocal
from models import Task
from tasks.runner import execute_task
from tasks.video_task import TaskStatus


def find_stuck_tasks(limit: int = 200) -> list[Task]:
    db = SessionLocal()
    try:
        return (
            db.query(Task)
            .filter(Task.status.in_([TaskStatus.PENDING.value, TaskStatus.RUNNING.value]))
            .order_by(Task.created_at.asc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def find_stuck_task_ids(limit: int = 200) -> list[str]:
    return [t.id for t in find_stuck_tasks(limit)]


def recover(limit: int = 200) -> list[str]:
    """重新执行 pending/running 任务（启动时调用）。返回**实际恢复**的 task_id 列表。

    P0-A 约束：
    - compose 任务在 ENABLE_COMPOSE=false 时跳过（受熔断锁约束，BUG-1）。
    - 已有 provider_job_id 的任务，火山侧已提交：runner 的 inflight 锁 + compose_service
      的续传逻辑保证不会重复 submit（BUG-2）。
    """
    recovered: list[str] = []
    for t in find_stuck_tasks(limit):
        if t.type == "compose" and not settings.enable_compose:
            continue  # 熔断锁未解锁 → 不重跑 compose（防暗烧/重复 submit）
        try:
            execute_task(t.id)  # runner 内 inflight 锁保证同一 task 只执行一次
            recovered.append(t.id)
        except Exception:  # noqa: BLE001  单任务失败不影响其它恢复
            pass
    return recovered


def recover_in_background() -> None:
    """在后台线程跑恢复，避免阻塞应用启动。"""
    import threading

    threading.Thread(target=recover, name="task-recovery", daemon=True).start()
