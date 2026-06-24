"""B3：进程内任务恢复。

当前为同进程后台执行（FastAPI BackgroundTasks）；进程重启（systemd restart）会丢失
未完成任务。启动时扫描 pending/running 任务并重新执行，避免任务永久卡死。

注：这是「至少恢复」机制；running 任务重跑可能产生重复副作用，故只对超时窗口外的
running 视为中断。真正的去重/断点续传可后续接 Celery/RQ。
"""

from __future__ import annotations

from db import SessionLocal
from models import Task
from tasks.runner import execute_task
from tasks.video_task import TaskStatus


def find_stuck_task_ids(limit: int = 200) -> list[str]:
    db = SessionLocal()
    try:
        rows = (
            db.query(Task.id)
            .filter(Task.status.in_([TaskStatus.PENDING.value, TaskStatus.RUNNING.value]))
            .order_by(Task.created_at.asc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    finally:
        db.close()


def recover(limit: int = 200) -> list[str]:
    """重新执行所有 pending/running 任务（启动时调用）。返回恢复的 task_id 列表。"""
    ids = find_stuck_task_ids(limit)
    for tid in ids:
        try:
            execute_task(tid)  # runner 内部各自开 session，幂等地置 running→done/failed
        except Exception:  # noqa: BLE001  单任务失败不影响其它恢复
            pass
    return ids


def recover_in_background() -> None:
    """在后台线程跑恢复，避免阻塞应用启动。"""
    import threading

    threading.Thread(target=recover, name="task-recovery", daemon=True).start()
