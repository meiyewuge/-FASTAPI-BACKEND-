"""正式观测接口 Mock 实现（W7）。

设计依据：M1-W7 条件施工许可 二.5。

Mock 实现全部内存化——**不写真实库、不起真实调度、不上报真实监控**。
供 W7 契约联调与 W8 沙盒替换真实实现前占位。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.app.content_factory.observability.schemas import DailyReport

from .protocols import AlertLevel, ScheduledJob


@dataclass
class MockReportStore:
    """内存日报存储（不写真实 DB）。"""

    is_mock: bool = True
    _reports: Dict[str, DailyReport] = field(default_factory=dict)

    def save_report(self, report: DailyReport) -> str:
        self._reports[report.date] = report
        return f"mock_report_{report.date}"

    def get_report(self, date: str) -> Optional[DailyReport]:
        return self._reports.get(date)

    def list_dates(self) -> List[str]:
        return sorted(self._reports.keys())


@dataclass
class MockScheduler:
    """内存调度器（只登记 job，不真正执行/不起线程）。"""

    is_mock: bool = True
    _jobs: List[ScheduledJob] = field(default_factory=list)

    def register(self, job: ScheduledJob) -> None:
        self._jobs.append(job)

    def list_jobs(self) -> List[ScheduledJob]:
        return list(self._jobs)


@dataclass
class MockAlertSink:
    """内存告警池（不上报真实监控平台）。"""

    is_mock: bool = True
    _alerts: List[Dict[str, str]] = field(default_factory=list)

    def emit(self, level: AlertLevel, kind: str, message: str) -> None:
        self._alerts.append({"level": level.value, "kind": kind, "message": message})

    def drain(self) -> List[Dict[str, str]]:
        out, self._alerts = self._alerts, []
        return out
