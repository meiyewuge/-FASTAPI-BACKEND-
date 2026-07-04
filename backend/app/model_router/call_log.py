"""模型调用日志与成本记录（设计第六章）。

- 每次调用（含失败）必记 14 个字段，缺一不可；
- 每日汇总成本；免费模型不计成本但仍记录次数和失败率；
- 单日成本超阈值 → 触发告警回调（stop 由熔断器执行，人工确认后解除）。

M1 mock 阶段为内存实现；持久化（结构化日志/产线日报对接）属 W6 工单。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .schemas import ModelRole

# 设计 6.1 规定的必记字段
REQUIRED_FIELDS = [
    "call_id", "timestamp", "model_role", "provider", "model_name",
    "input_tokens", "output_tokens", "cost", "latency_ms",
    "success", "fail_reason", "content_id", "used_materials_ids", "g1_result",
]


@dataclass
class CallLogEntry:
    call_id: str
    timestamp: str
    model_role: str
    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int
    success: bool
    fail_reason: Optional[str]
    content_id: str
    used_materials_ids: List[str]
    g1_result: Optional[str]


@dataclass
class CallLog:
    """内存调用日志 + 当日成本汇总。"""

    daily_cost_limit: Optional[float] = None
    on_cost_alert: Optional[Callable[[float, float], None]] = None
    entries: List[CallLogEntry] = field(default_factory=list)

    def record(
        self,
        *,
        model_role: ModelRole,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cost_per_1k_tokens: Optional[float],
        latency_ms: int,
        success: bool,
        fail_reason: Optional[str],
        content_id: str,
        used_materials_ids: List[str],
        g1_result: Optional[str],
    ) -> CallLogEntry:
        # 免费模型（cost_per_1k_tokens 为 0 或 None=待定）不计成本，但照常记录次数/失败率
        rate = cost_per_1k_tokens or 0.0
        cost = round((input_tokens + output_tokens) / 1000.0 * rate, 6)
        entry = CallLogEntry(
            call_id=f"call_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            model_role=model_role.value,
            provider=provider,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            latency_ms=latency_ms,
            success=success,
            fail_reason=fail_reason,
            content_id=content_id,
            used_materials_ids=list(used_materials_ids),
            g1_result=g1_result,
        )
        self.entries.append(entry)
        if self.daily_cost_limit is not None and self.on_cost_alert:
            today = self.daily_cost_total()
            if today > self.daily_cost_limit:
                self.on_cost_alert(today, self.daily_cost_limit)
        return entry

    # ── 汇总 ──
    def daily_cost_total(self, day: Optional[str] = None) -> float:
        """当日（UTC）成本合计。day 形如 '2026-07-04'，默认今天。"""
        day = day or datetime.now(timezone.utc).date().isoformat()
        return round(sum(e.cost for e in self.entries if e.timestamp.startswith(day)), 6)

    def stats_by_model(self) -> Dict[str, Dict[str, float]]:
        """按模型统计调用次数与失败率（含免费模型）。"""
        out: Dict[str, Dict[str, float]] = {}
        for e in self.entries:
            s = out.setdefault(e.model_name, {"calls": 0, "failures": 0, "cost": 0.0})
            s["calls"] += 1
            s["cost"] = round(s["cost"] + e.cost, 6)
            if not e.success:
                s["failures"] += 1
        for s in out.values():
            s["fail_rate"] = round(s["failures"] / s["calls"], 4) if s["calls"] else 0.0
        return out

    def calls_for_content(self, content_id: str) -> int:
        return sum(1 for e in self.entries if e.content_id == content_id)
