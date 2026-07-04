"""硬边界四：模型失败熔断（设计 8.4）。

熔断触发条件（草案阈值）：
- 主模型连续失败 ≥3 次        → hold，切 fallback_model
- 主模型+fallback 双失败 ≥1 次 → stop，进入 manual_review
- G1 连续 fail ≥3 次同一内容   → stop，进入 manual_review
- 质量评分连续低于门槛 ≥3 次   → hold，进入 manual_review
- 单日成本超阈值               → stop，告警+人工确认
- 单篇文案模型调用次数 ≥5 次   → stop，进入 manual_review

熔断纪律：
- 熔断后不得自动恢复，必须人工确认后解除（release 需操作人+原因）
- 熔断原因必须记录（trip_history 供调用日志/日报采集）
- 熔断期间同类型任务排队等待（queued_tasks），不丢弃
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

PRIMARY_CONSECUTIVE_FAIL_THRESHOLD = 3
QUALITY_LOW_STREAK_THRESHOLD = 3
G1_FAIL_PER_CONTENT_THRESHOLD = 3


class CircuitOpenError(Exception):
    """熔断中，任务应排队等待人工确认，不得继续调用模型。"""

    def __init__(self, action: str, reason: str):
        super().__init__(f"circuit {action}: {reason}")
        self.action = action  # "hold" / "stop"
        self.reason = reason


@dataclass
class TripRecord:
    timestamp: str
    action: str          # hold / stop
    reason: str
    released_by: Optional[str] = None
    release_note: Optional[str] = None


@dataclass
class CircuitBreaker:
    state: str = "closed"                  # closed / hold / stop
    trip_history: List[TripRecord] = field(default_factory=list)
    queued_tasks: List[str] = field(default_factory=list)   # 熔断期间排队的 content_id，不丢弃

    # 连续计数器
    _primary_fail_streak: int = 0
    _quality_low_streak: int = 0
    _g1_fail_by_content: Dict[str, int] = field(default_factory=dict)

    # ── 状态查询 ──
    @property
    def is_open(self) -> bool:
        return self.state != "closed"

    def check_or_queue(self, content_id: str) -> None:
        """熔断中则把任务排队并抛 CircuitOpenError（不丢弃、不静默跳过）。"""
        if self.is_open:
            self.queued_tasks.append(content_id)
            last = self.trip_history[-1]
            raise CircuitOpenError(self.state, last.reason)

    # ── 触发入口 ──
    def _trip(self, action: str, reason: str) -> None:
        self.state = action
        self.trip_history.append(
            TripRecord(timestamp=datetime.now(timezone.utc).isoformat(), action=action, reason=reason)
        )

    def on_primary_failure(self) -> None:
        self._primary_fail_streak += 1
        if self._primary_fail_streak >= PRIMARY_CONSECUTIVE_FAIL_THRESHOLD:
            self._trip("hold", f"主模型连续失败≥{PRIMARY_CONSECUTIVE_FAIL_THRESHOLD}次")

    def on_primary_success(self) -> None:
        self._primary_fail_streak = 0

    def on_double_failure(self, content_id: str) -> None:
        """主模型+fallback 双失败 ≥1 次 → stop，进入 manual_review。"""
        self._trip("stop", f"主模型+fallback双失败(content_id={content_id})")

    def on_g1_fail(self, content_id: str) -> None:
        n = self._g1_fail_by_content.get(content_id, 0) + 1
        self._g1_fail_by_content[content_id] = n
        if n >= G1_FAIL_PER_CONTENT_THRESHOLD:
            self._trip("stop", f"G1连续fail≥{G1_FAIL_PER_CONTENT_THRESHOLD}次(content_id={content_id})")

    def on_quality_low(self) -> None:
        self._quality_low_streak += 1
        if self._quality_low_streak >= QUALITY_LOW_STREAK_THRESHOLD:
            self._trip("hold", f"质量评分连续低于门槛≥{QUALITY_LOW_STREAK_THRESHOLD}次")

    def on_quality_ok(self) -> None:
        self._quality_low_streak = 0

    def on_cost_exceeded(self, today_cost: float, limit: float) -> None:
        self._trip("stop", f"单日模型成本{today_cost}超阈值{limit}")

    def on_calls_exceeded(self, content_id: str, calls: int, limit: int) -> None:
        self._trip("stop", f"单篇文案模型调用次数{calls}≥{limit}(content_id={content_id})")

    # ── 人工解除（唯一恢复通道，不自动恢复） ──
    def release(self, operator: str, note: str) -> List[str]:
        """人工确认后解除熔断，返回排队任务清单交回队列。"""
        if not operator or not note:
            raise ValueError("熔断解除必须记录操作人与原因，不得静默恢复")
        if self.trip_history:
            self.trip_history[-1].released_by = operator
            self.trip_history[-1].release_note = note
        self.state = "closed"
        self._primary_fail_streak = 0
        self._quality_low_streak = 0
        self._g1_fail_by_content.clear()
        queued, self.queued_tasks = self.queued_tasks, []
        return queued
