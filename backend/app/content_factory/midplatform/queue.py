"""candidate_review 候选审读队列（W5，内存 mock）。

设计依据：M1-W5 条件施工许可 二.2 + 五·必测 11。

铁律：
- 队列只在内存（mock），**不写正式知识库、不写 approved、不 reindex**（必测 11）；
- 入队仅接受 W4 ReviewPackagePre；缺料/门拦截由 adapter 转前台提示（必测 12/13）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.app.content_factory.gates.review_package import ReviewPackagePre

from .detail import build_review_package_detail, map_review_state
from .schemas import CandidateReviewEntry, CandidateReviewState
from .state_machine import settle_from_review


@dataclass
class CandidateReviewQueue:
    """候选审读队列。仅内存字典，绝不落正式库。"""

    _entries: Dict[str, CandidateReviewEntry] = field(default_factory=dict)

    def enqueue(self, pkg: ReviewPackagePre, platform: Optional[str] = None) -> CandidateReviewEntry:
        """从 W4 ReviewPackagePre 入队。入队即由裁决结果落位。"""
        detail = build_review_package_detail(pkg)
        entry = CandidateReviewEntry(
            content_id=pkg.content_id,
            brief_id=pkg.brief_id,
            trace_id=pkg.trace_id,
            state=CandidateReviewState.PENDING_REVIEW,
            must_sign=pkg.must_sign,
            platform=platform,
            detail=detail,
        )
        # PENDING_REVIEW → 裁决落位（ready/needs_human/blocked）
        settle_from_review(entry, map_review_state(pkg.review_status))
        self._entries[entry.content_id] = entry
        return entry

    def get(self, content_id: str) -> Optional[CandidateReviewEntry]:
        return self._entries.get(content_id)

    def list_all(self) -> List[CandidateReviewEntry]:
        return list(self._entries.values())

    def list_by_state(self, state: CandidateReviewState) -> List[CandidateReviewEntry]:
        return [e for e in self._entries.values() if e.state == state]

    def count_by_state(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self._entries.values():
            out[e.state.value] = out.get(e.state.value, 0) + 1
        return out

    def count(self) -> int:
        return len(self._entries)
