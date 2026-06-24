"""任务系统（独立模块）：创建 / 查询 / 状态流转 / retry。

异步执行见 tasks.runner。状态机：pending → running → done | failed。
"""

from __future__ import annotations

import json
import uuid
from enum import Enum

from sqlalchemy.orm import Session

from models import Task


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def create_task(
    db: Session, tenant_id: str, ttype: str, payload: dict, store_id: int | None = None
) -> Task:
    task = Task(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        store_id=store_id,
        type=ttype,
        status=TaskStatus.PENDING.value,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, tenant_id: str, task_id: str) -> Task | None:
    return (
        db.query(Task)
        .filter(Task.id == task_id, Task.tenant_id == tenant_id)
        .first()
    )


def get_task_any(db: Session, task_id: str) -> Task | None:
    return db.get(Task, task_id)


def list_tasks(db: Session, tenant_id: str, limit: int = 50) -> list[Task]:
    return (
        db.query(Task)
        .filter(Task.tenant_id == tenant_id)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )


def set_status(
    db: Session,
    task_id: str,
    status: str,
    progress: float | None = None,
    result: str | None = None,
    error: str | None = None,
    inc_retry: bool = False,
) -> None:
    task = db.get(Task, task_id)
    if task is None:
        return
    task.status = status
    if progress is not None:
        task.progress = progress
    if result is not None:
        task.result = result
    if error is not None:
        task.error = error
    if inc_retry:
        task.retry_count = (task.retry_count or 0) + 1
    db.commit()
