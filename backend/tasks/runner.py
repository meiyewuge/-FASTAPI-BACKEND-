"""后台任务执行器。

当前：同进程后台执行（FastAPI BackgroundTasks 调度），各执行体独立 DB 会话。
未来：把 execute_task 投递到 Celery/RQ/Arq 队列即可，调用方无需改动。
"""

from __future__ import annotations

import json
import threading

from db import SessionLocal
from services import orchestrator
from tasks import video_task
from tasks.video_task import TaskStatus

# V4 P0-A（BUG-1）：同一 task_id 只能执行一次（防 recovery / 双触发重复执行火山）
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def _acquire(task_id: str) -> bool:
    with _inflight_lock:
        if task_id in _inflight:
            return False
        _inflight.add(task_id)
        return True


def _release(task_id: str) -> None:
    with _inflight_lock:
        _inflight.discard(task_id)


def execute_task(task_id: str) -> None:
    if not _acquire(task_id):
        return  # 已在执行中 → 跳过（幂等，防重复 submit）
    db = SessionLocal()
    try:
        task = video_task.get_task_any(db, task_id)
        if task is None:
            return
        payload = json.loads(task.payload or "{}")
        video_task.set_status(db, task_id, TaskStatus.RUNNING.value, progress=0.1)
        result = orchestrator.run(db, task, payload)
        video_task.set_status(
            db,
            task_id,
            TaskStatus.DONE.value,
            progress=1.0,
            result=json.dumps(result, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001  失败落库，便于 retry
        db.rollback()
        video_task.set_status(
            db, task_id, TaskStatus.FAILED.value, error=str(exc), inc_retry=True
        )
        # BUG-2：任务失败 → 自动退回已预扣费用
        try:
            from cost_engine import cost_ledger
            cost_ledger.refund(db, task_id, reason="failed")
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        # V4 P0：回填工作流记录（不影响主任务流程）
        try:
            from services import reflow_service
            reflow_service.finalize_for_task(db, task_id)
        except Exception:  # noqa: BLE001
            db.rollback()
        db.close()
        _release(task_id)


def dispatch_compose(task_id: str) -> None:
    """BUG-1：compose 用独立 daemon 线程执行，不占用 uvicorn 线程池（避免长轮询卡死）。"""
    threading.Thread(target=execute_task, args=(task_id,), name=f"compose-{task_id}",
                     daemon=True).start()


def retry_task(task_id: str) -> None:
    """重试：仅对 failed 任务，重置为 pending 后重新执行。"""
    db = SessionLocal()
    try:
        task = video_task.get_task_any(db, task_id)
        if task is None or task.status != TaskStatus.FAILED.value:
            return
        video_task.set_status(db, task_id, TaskStatus.PENDING.value, progress=0.0, error="")
    finally:
        db.close()
    execute_task(task_id)
