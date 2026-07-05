"""W7 正式观测接口契约子包（M1 条件施工 · 骨架阶段）。

设计依据：M1-W7 条件施工许可 二.5。

只做 Protocol 契约 + Mock 实现——**不接真实数据库、真实调度器、真实监控平台**：
- ReportStore：日报持久化契约（Mock 用内存 dict）；
- Scheduler：定时触发契约（Mock 记录注册，不真正起线程/进程）；
- AlertSink：告警上报契约（Mock 收集到内存列表）。

正式实现（DB/调度器/监控 SDK）在 W8 联调沙盒后，按 feature flag 逐步接入。
"""
from .protocols import AlertSink, Scheduler, ReportStore, ScheduledJob, AlertLevel
from .mocks import MockAlertSink, MockReportStore, MockScheduler

__all__ = [
    "AlertLevel",
    "AlertSink",
    "MockAlertSink",
    "MockReportStore",
    "MockScheduler",
    "ReportStore",
    "ScheduledJob",
    "Scheduler",
]
