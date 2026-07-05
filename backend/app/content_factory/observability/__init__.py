"""W6 产线日报与运行观测子包（M1 条件施工 · 骨架阶段）。

设计依据：M1-W6 条件施工许可。

本子包为纯库层 mock 观测：
- 只读聚合 factory 运行结果 + candidate_review 队列态 → 每日日报 + 异常观测；
- **不接真实监控平台、不写真实数据库、不接真实定时任务、不接真实模型/9080**；
- 不挂 FastAPI、不开 /content/generate、不触 9200/reindex/site_published；
- marked_ready_to_publish 计为"备发标记数"（≠发布量）；candidate_review 计数（≠approved 量）。

模块：
- schemas.py：RunObservation / DailyReport / AnomalyFlag / RunOutcome / AnomalyKind
- observer.py：ProductionLineObserver（观测累积 + 队列态快照）
- report.py：build_daily_report + 异常观测（AnomalyThresholds）
"""
from .schemas import (
    AnomalyFlag,
    AnomalyKind,
    DailyReport,
    RunObservation,
    RunOutcome,
)
from .observer import ProductionLineObserver
from .report import AnomalyThresholds, build_daily_report

__all__ = [
    "AnomalyFlag",
    "AnomalyKind",
    "AnomalyThresholds",
    "DailyReport",
    "ProductionLineObserver",
    "RunObservation",
    "RunOutcome",
    "build_daily_report",
]
