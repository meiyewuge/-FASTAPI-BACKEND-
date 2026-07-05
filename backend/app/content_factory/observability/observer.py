"""产线运行观测器（W6，内存 mock）。

设计依据：M1-W6 条件施工许可 二.1/二.2。

职责：
- 接收 factory 处理结果 → 累积 RunObservation；
- 快照 candidate_review 队列态计数；
- 全部内存聚合，**不写真实库、不接真实监控、不接定时任务**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

from .schemas import RunObservation

if TYPE_CHECKING:
    from backend.app.content_factory.factory import FactoryResult
    from backend.app.content_factory.midplatform.queue import CandidateReviewQueue


@dataclass
class ProductionLineObserver:
    """content_factory 产线运行观测器。"""

    observations: List[RunObservation] = field(default_factory=list)
    # candidate_review 队列态计数快照（人审动线产生的态：needs_human/marked_ready/rejected...）
    review_state_counts: Dict[str, int] = field(default_factory=dict)

    def observe(self, factory_result: "FactoryResult") -> RunObservation:
        """观测一次 factory 运行结果。"""
        obs = RunObservation.from_factory_result(factory_result)
        self.observations.append(obs)
        return obs

    def observe_many(self, results: List["FactoryResult"]) -> None:
        for r in results:
            self.observe(r)

    def snapshot_review_queue(self, queue: "CandidateReviewQueue") -> Dict[str, int]:
        """快照审读队列各态计数（只读）。"""
        self.review_state_counts = queue.count_by_state()
        return self.review_state_counts

    # ── 只读聚合辅助 ─────────────────────────────────────────────
    def count_by_outcome(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for o in self.observations:
            out[o.outcome.value] = out.get(o.outcome.value, 0) + 1
        return out

    @property
    def brief_count(self) -> int:
        # 以 brief_id 去重计 brief 数（一条 brief 可能多次观测时不重复计）
        return len({o.brief_id for o in self.observations})

    @property
    def run_count(self) -> int:
        return len(self.observations)
