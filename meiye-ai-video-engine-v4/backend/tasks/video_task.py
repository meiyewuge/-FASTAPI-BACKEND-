"""任务系统（独立模块，skeleton）。

视频生成为长耗时操作，必须在此异步执行，API 层只投递 + 查询状态。
后续可接 Celery / RQ / Arq 等队列；当前仅定义状态枚举与接口占位。
"""

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def submit_mother_video_task(tenant_id: str, prompt: str) -> str:
    """A台：投递母视频生成任务，返回 task_id。"""
    raise NotImplementedError


def submit_viral_video_task(tenant_id: str, source_video_id: str, count: int) -> str:
    """B台：投递混剪裂变任务，返回 task_id。"""
    raise NotImplementedError


def get_task_status(tenant_id: str, task_id: str) -> dict:
    """查询任务状态与产出。"""
    raise NotImplementedError
