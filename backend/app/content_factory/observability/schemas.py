"""W6 产线日报与运行观测数据结构。

设计依据：M1-W6 条件施工许可 一/二/五/六。

层次：
- 单次运行 → RunObservation（一条 brief 处理结果的观测切片）
- 每日聚合 → DailyReport（指标 + 异常观测 + 按结果/审读态分布）

铁律（许可三·严禁 15/16）：
- marked_ready_to_publish 是"备发标记数"，**不是发布量**；
- candidate_review 计数**不是 approved 量**；
- 本层纯内存聚合，不写真实库、不接真实监控、不接真实定时任务。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# 单次运行结果分类
# ──────────────────────────────────────────────────────────────────────
class RunOutcome(str, Enum):
    """一次 content_factory 运行的终态分类（观测口径）。"""

    PACKAGED = "packaged"                              # 出候选，进审读
    HALTED_MISSING_MATERIALS = "halted_missing_materials"  # 缺料停单
    BLOCKED_DRAFT = "blocked_draft"                    # 草稿被拦（无源/新增事实）
    GATE_BLOCKED = "gate_blocked"                      # 门检拦截
    OTHER = "other"                                    # 其它/未终结


# ──────────────────────────────────────────────────────────────────────
# 异常观测类型（许可六）
# ──────────────────────────────────────────────────────────────────────
class AnomalyKind(str, Enum):
    NO_RECALL_CLIENT = "no_recall_client"              # 无 recall_client
    MISSING_AFTER_FILTER = "missing_after_filter"      # 黑名单过滤后缺料
    HIGH_G1_G3_FAIL = "high_g1_g3_fail"                # G1/G3 fail 高发
    LOOP_EXHAUSTED = "loop_exhausted"                  # loop 3 圈耗尽
    HUMAN_REVIEW_BACKLOG = "human_review_backlog"      # 人审积压


@dataclass
class AnomalyFlag:
    """单条异常观测。"""

    kind: AnomalyKind
    count: int
    detail: str
    severity: str = "warning"   # info / warning / high


# ──────────────────────────────────────────────────────────────────────
# 单次运行观测切片
# ──────────────────────────────────────────────────────────────────────
@dataclass
class RunObservation:
    """一次 factory 处理结果的观测切片（从 FactoryResult 提炼）。"""

    content_id: str
    brief_id: str
    trace_id: str
    outcome: RunOutcome
    recall_status: str = ""
    had_recall_client: bool = True
    g1_fail_count: int = 0
    g3_fail_count: int = 0
    loop_rounds_used: int = 0
    loop_converged: bool = True

    @classmethod
    def from_factory_result(cls, result) -> "RunObservation":
        """从 FactoryResult 提炼观测切片（只读，不改 result）。"""
        from backend.app.content_factory.schemas import FactoryTaskState

        state_map = {
            FactoryTaskState.PACKAGED: RunOutcome.PACKAGED,
            FactoryTaskState.HALTED_MISSING_MATERIALS: RunOutcome.HALTED_MISSING_MATERIALS,
            FactoryTaskState.BLOCKED_DRAFT: RunOutcome.BLOCKED_DRAFT,
            FactoryTaskState.GATE_BLOCKED: RunOutcome.GATE_BLOCKED,
        }
        outcome = state_map.get(result.state, RunOutcome.OTHER)
        recall_status = (result.recall_summary or {}).get("status", "")

        g1 = g3 = rounds = 0
        converged = True
        if result.gate_report is not None:
            for vr in result.gate_report.version_reports:
                for gr in vr.results:
                    if gr.verdict.value == "fail" and gr.gate.value == "G1_compliance":
                        g1 += 1
                    if gr.verdict.value == "fail" and gr.gate.value == "G3_fact_ref":
                        g3 += 1
            rounds = result.gate_report.loop_result.rounds_used
            converged = result.gate_report.loop_result.converged

        return cls(
            content_id=result.content_id,
            brief_id=result.brief_id,
            trace_id=result.trace_id,
            outcome=outcome,
            recall_status=recall_status,
            had_recall_client=recall_status != "recall_client_not_configured",
            g1_fail_count=g1,
            g3_fail_count=g3,
            loop_rounds_used=rounds,
            loop_converged=converged,
        )


# ──────────────────────────────────────────────────────────────────────
# 每日日报
# ──────────────────────────────────────────────────────────────────────
@dataclass
class DailyReport:
    """每日产线日报（mock 输出）。

    metrics：许可五·运行观测指标（7 项 + 观测扩展）。
    review_state_counts：candidate_review 各态计数（≠ approved 量）。
    """

    date: str
    metrics: Dict[str, int] = field(default_factory=dict)
    by_outcome: Dict[str, int] = field(default_factory=dict)
    review_state_counts: Dict[str, int] = field(default_factory=dict)
    anomalies: List[AnomalyFlag] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "metrics": self.metrics,
            "by_outcome": self.by_outcome,
            "review_state_counts": self.review_state_counts,
            "anomalies": [
                {"kind": a.kind.value, "count": a.count, "severity": a.severity, "detail": a.detail}
                for a in self.anomalies
            ],
        }
