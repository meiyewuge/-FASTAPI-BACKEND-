"""成本与控制层数据模型（T2B）。

包含：
    CostRecord         — 单条成本记录
    DailyCostSummary   — 单日成本汇总
    CircuitState       — 熔断/控制状态枚举
    CostCheckResult    — 成本检查结果
    FallbackLevel      — F1/F2/F3 fallback 层级枚举
    PauseReason        — Provider 暂停原因枚举

⚠️ T2B 阶段：纯内存 / 临时 SQLite 数据结构，不写生产库、不联网、不发真实通知。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    """成本熔断 / 控制状态（蛇形命名）。"""
    OK = "ok"
    COST_EXCEEDED = "cost_exceeded"          # 单次任务超限
    SWITCH_FREE = "switch_free"              # 单日超限 → 切免费源
    SWITCH_FREE_NOTIFY = "switch_free_notify"  # 单月超限 → 切免费源 + 通知
    PROVIDER_PAUSED = "provider_paused"      # Provider 被暂停（日上限/连续失败）


class PauseReason(str, Enum):
    """Provider 暂停原因。"""
    NONE = "none"
    PROVIDER_DAILY_LIMIT = "provider_daily_limit"      # 日成本上限 → 暂停 1 小时
    CONSECUTIVE_FAILURES = "consecutive_failures"      # 连续失败 → 暂停 30 分钟


class FallbackLevel(str, Enum):
    """Fallback 层级骨架（不做 T5 主路由）。

    F1 = 主搜 / 同类 primary fallback（Bocha / Tavily）
    F2 = 低成本 fallback（GLM 免费源）
    F3 = 紧急 codeact fallback（仅标记，本阶段不真实调用 codeact）
    """
    F1_PRIMARY = "f1_primary"
    F2_LOW_COST = "f2_low_cost"
    F3_EMERGENCY = "f3_emergency"


@dataclass
class CostCheckResult:
    """成本检查结果。

    allowed: 是否允许本次调用 / 当前是否处于正常额度内。
    state: CircuitState 值。
    error_code: 命中熔断时的错误码（如 cost_exceeded），否则 none。
    should_switch_free: 是否应切免费源（日/月超限）。
    should_notify / notification_required: 是否需要通知吴哥（月超限；
        仅返回标志，**不接真实飞书通知**）。
    reason: 文本说明。
    """
    allowed: bool = True
    state: str = CircuitState.OK.value
    error_code: str = "none"
    should_switch_free: bool = False
    should_notify: bool = False
    notification_required: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "state": self.state,
            "error_code": self.error_code,
            "should_switch_free": self.should_switch_free,
            "should_notify": self.should_notify,
            "notification_required": self.notification_required,
            "reason": self.reason,
        }


@dataclass
class CostRecord:
    """单条成本记录。"""
    timestamp: str                  # ISO8601，如 "2026-06-27T08:30:00"
    provider: str
    task_type: str
    cost: float
    success: bool = True
    error_code: str = "none"
    credits_used: int = 0
    id: int | None = None           # SQLite 自增主键（持久化后回填）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "task_type": self.task_type,
            "cost": round(self.cost, 4),
            "success": self.success,
            "error_code": self.error_code,
            "credits_used": self.credits_used,
        }


@dataclass
class DailyCostSummary:
    """单日成本汇总。"""
    date: str                                    # "2026-06-27"
    total_cost: float = 0.0
    record_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    per_provider_cost: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "total_cost": round(self.total_cost, 4),
            "record_count": self.record_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "per_provider_cost": {k: round(v, 4) for k, v in self.per_provider_cost.items()},
        }
