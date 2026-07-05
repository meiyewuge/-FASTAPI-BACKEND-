"""W8 沙盒结果数据结构。

设计依据：M1-W8 条件施工许可 二.8/二.9。

铁律：
- sandbox_result 是联调沙盒的只读结果，不是生产可用信号；
- is_sandbox_pass 仅表示"全 mock 链路跑通"，不等于可上线；
- publish_allowed / writes_approved 恒 False（与 DraftCandidate/CandidateGateReport 口径一致）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.app.content_factory.schemas import FactoryTaskState


class SandboxPathKind(str, Enum):
    """沙盒运行路径分类（六种典型路径）。"""

    SUCCESS = "success"                          # 成功路径：PACKAGED
    MISSING_MATERIALS = "missing_materials"      # 缺料停单：HALTED_MISSING_MATERIALS
    BLOCKED_DRAFT = "blocked_draft"              # 草稿拦截：BLOCKED_DRAFT
    GATE_BLOCKED = "gate_blocked"                # 门检拦截：GATE_BLOCKED
    HUMAN_REVIEW = "human_review"                # 人审路径：needs_human_review
    DAILY_REPORT = "daily_report"                # 日报路径：build_daily_report


@dataclass
class SandboxResult:
    """沙盒单次运行结果。

    铁律：sandbox pass ≠ 生产可用。
    publish_allowed / writes_approved 恒 False（无写入口）。
    """

    path: SandboxPathKind
    factory_state: FactoryTaskState
    content_id: str
    brief_id: str
    trace_id: str
    text: Optional[str] = None
    recall_summary: Dict[str, Any] = field(default_factory=dict)
    used_materials_ids: List[str] = field(default_factory=list)
    gate_review_status: Optional[str] = None
    review_queue_state: Optional[str] = None
    daily_report: Optional[Dict[str, Any]] = None
    # ── 常量出口约束 ──
    publish_allowed: bool = field(default=False, init=False)
    writes_approved: bool = field(default=False, init=False)

    @property
    def is_sandbox_pass(self) -> bool:
        """沙盒链路跑通（不等于可上线）：factory 到达预期终态。"""
        terminal = {
            FactoryTaskState.PACKAGED,
            FactoryTaskState.HALTED_MISSING_MATERIALS,
            FactoryTaskState.BLOCKED_DRAFT,
            FactoryTaskState.GATE_BLOCKED,
        }
        return self.factory_state in terminal

    @property
    def is_production_signal(self) -> bool:
        """恒 False：沙盒 pass 不等于生产可用信号。"""
        return False
