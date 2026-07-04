"""任务状态机 — 6 态流转 + 合法转换约束。

设计依据：M1 W1 服务骨架。

6 态流转：queued → producing → gated → packaged → in_review → closed
不允许跳态（如 queued → closed），不允许倒退。
每次转换记录时间戳和操作人（history）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .schemas import FactoryTaskState


class InvalidTransition(ValueError):
    """非法状态转换。"""


# ── 合法转换表（设计文档 W1 §3）──────────────────────────────────────
# 只允许相邻前向流转；closed 为终态，不可再转换。
_ALLOWED_TRANSITIONS = {
    FactoryTaskState.QUEUED: {FactoryTaskState.PRODUCING},
    FactoryTaskState.PRODUCING: {FactoryTaskState.GATED},
    FactoryTaskState.GATED: {FactoryTaskState.PACKAGED},
    FactoryTaskState.PACKAGED: {FactoryTaskState.IN_REVIEW},
    FactoryTaskState.IN_REVIEW: {FactoryTaskState.CLOSED},
    FactoryTaskState.CLOSED: set(),  # 终态
}


@dataclass
class TransitionRecord:
    """一次状态转换记录。"""

    from_state: FactoryTaskState
    to_state: FactoryTaskState
    timestamp: str
    operator: str
    note: Optional[str] = None


@dataclass
class StateMachine:
    """任务状态机。

    持有当前状态和转换历史。
    不自动流转——每次转换必须由调用方显式触发。
    """

    current: FactoryTaskState = FactoryTaskState.QUEUED
    history: List[TransitionRecord] = field(default_factory=list)

    def transition(
        self, target: FactoryTaskState, operator: str = "system", note: Optional[str] = None
    ) -> FactoryTaskState:
        """执行状态转换。

        非法转换 → 抛 InvalidTransition。
        返回转换后的新状态。
        """
        allowed = _ALLOWED_TRANSITIONS.get(self.current, set())
        if target not in allowed:
            raise InvalidTransition(
                f"非法状态转换: {self.current.value} → {target.value}，"
                f"当前允许: {[s.value for s in allowed]}"
            )
        record = TransitionRecord(
            from_state=self.current,
            to_state=target,
            timestamp=datetime.now(timezone.utc).isoformat(),
            operator=operator,
            note=note,
        )
        self.history.append(record)
        self.current = target
        return self.current

    @property
    def is_terminal(self) -> bool:
        """是否已到终态。"""
        return self.current == FactoryTaskState.CLOSED

    @property
    def allowed_next(self) -> List[FactoryTaskState]:
        """当前状态允许的下一步。"""
        return sorted(_ALLOWED_TRANSITIONS.get(self.current, set()), key=lambda s: s.value)
