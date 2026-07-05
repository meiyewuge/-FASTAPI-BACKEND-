"""正式观测接口 Protocol 契约（W7）。

设计依据：M1-W7 条件施工许可 二.5。

只定契约，不定实现。真实实现（DB / 调度器 / 监控）须实现这些 Protocol，
且受 REAL_OBSERVABILITY_ENABLED feature flag 门控（默认 False）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Protocol

from backend.app.content_factory.observability.schemas import DailyReport


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"


@dataclass
class ScheduledJob:
    """一个已注册的定时任务（契约层，不含真实调度实现）。"""

    job_id: str
    cron: str            # 形如 "0 9 * * *"（每日 9 点）——契约占位，Mock 不解析执行
    description: str = ""


class ReportStore(Protocol):
    """日报持久化契约。真实实现写 DB；Mock 写内存。"""

    def save_report(self, report: DailyReport) -> str:
        """持久化一份日报，返回存储 ID。"""
        ...

    def get_report(self, date: str) -> Optional[DailyReport]:
        ...

    def list_dates(self) -> List[str]:
        ...


class Scheduler(Protocol):
    """定时触发契约。真实实现接 cron/apscheduler；Mock 只登记不执行。"""

    def register(self, job: ScheduledJob) -> None:
        ...

    def list_jobs(self) -> List[ScheduledJob]:
        ...


class AlertSink(Protocol):
    """告警上报契约。真实实现接监控平台；Mock 收集到内存。"""

    def emit(self, level: AlertLevel, kind: str, message: str) -> None:
        ...

    def drain(self) -> List[Dict[str, str]]:
        """取出并清空已收集告警（Mock 用）。"""
        ...
