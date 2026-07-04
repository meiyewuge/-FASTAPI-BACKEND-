"""内容经营中台 · 三页一弹窗 mock 联动（W5）。

设计依据：M1-W5 条件施工许可 二.8/二.9 + 五·必测 12/13。

三页：Brief 下单页 / 审读台 / 产线日报；一弹窗：审读包详情。
全部为 mock 视图模型（返回 dict/dataclass），**不挂 FastAPI、不写库、不发布**。

前台提示（必测 12/13）：
- 缺料停单（HALTED_MISSING_MATERIALS）→ 缺料提示；
- 门拦截（GATE_BLOCKED / BLOCKED_DRAFT）→ blocked 提示；
- needs_human_review → 人工审读提示。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.app.content_factory.gates.review_package import build_review_package_pre

from .detail import build_review_package_detail
from .queue import CandidateReviewQueue
from .schemas import CandidateReviewEntry, CandidateReviewState, ReviewPackageDetail
from .state_machine import (
    mark_ready_to_publish,
    reject_for_revision,
    submit_for_signoff,
)

if TYPE_CHECKING:
    from backend.app.content_factory.factory import FactoryResult


@dataclass
class FrontdeskNotice:
    """前台提示（非入队的异常态）。"""

    content_id: str
    kind: str        # missing_materials / blocked / gate_blocked
    message: str


@dataclass
class MidPlatformMock:
    """内容经营中台 mock 联动骨架。"""

    queue: CandidateReviewQueue = field(default_factory=CandidateReviewQueue)
    notices: List[FrontdeskNotice] = field(default_factory=list)

    # ── 联动入口：把 factory 结果分流到队列 / 前台提示 ──────────────
    def ingest_factory_result(self, result: "FactoryResult"):
        """把一次 factory 处理结果接入中台。

        - PACKAGED + gate_report → 构造 ReviewPackagePre 入队；
        - HALTED_MISSING_MATERIALS → 缺料前台提示（必测 12）；
        - GATE_BLOCKED / BLOCKED_DRAFT → blocked 前台提示（必测 13）。
        返回 CandidateReviewEntry 或 FrontdeskNotice。
        """
        from backend.app.content_factory.schemas import FactoryTaskState

        state = result.state
        if state == FactoryTaskState.HALTED_MISSING_MATERIALS:
            notice = FrontdeskNotice(
                content_id=result.content_id, kind="missing_materials",
                message="⛔ 缺料停单：素材不足/未配置召回，请补料后重下单。",
            )
            self.notices.append(notice)
            return notice
        if state in (FactoryTaskState.GATE_BLOCKED, FactoryTaskState.BLOCKED_DRAFT):
            notice = FrontdeskNotice(
                content_id=result.content_id, kind="blocked",
                message="⛔ 候选被拦截（门/草稿），不可备发，请驳回修改。",
            )
            self.notices.append(notice)
            return notice
        # 正常打包 → 需 gate_report + draft_candidate 构造前置包
        if result.gate_report is not None and result.draft_candidate is not None:
            pkg = build_review_package_pre(result.draft_candidate, result.gate_report)
            return self.queue.enqueue(pkg, platform=None)
        # 无门报告（未接 pipeline）→ 不入审读队列
        return None

    # ── 页 1：Brief 下单页（mock 视图）────────────────────────────
    def brief_order_page(self, brief_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Brief 下单页 mock：仅回执，不触发真实产线（骨架）。"""
        return {
            "page": "brief_order",
            "accepted": bool(brief_dict.get("raw_text") and brief_dict.get("target_platform")),
            "hint": "下单后进入产线；缺料/门拦截会在审读台以前台提示呈现。",
        }

    # ── 页 2：审读台（mock 视图）──────────────────────────────────
    def review_desk_page(self, state_filter: Optional[CandidateReviewState] = None) -> Dict[str, Any]:
        """审读台 mock：列出候选 + 筛选 + 前台提示。"""
        entries = (self.queue.list_by_state(state_filter) if state_filter
                   else self.queue.list_all())
        return {
            "page": "review_desk",
            "counts": self.queue.count_by_state(),
            "items": [self._row(e) for e in entries],
            "notices": [{"content_id": n.content_id, "kind": n.kind, "message": n.message}
                        for n in self.notices],
        }

    # ── 弹窗：审读包详情 ──────────────────────────────────────────
    def open_detail_modal(self, content_id: str) -> Optional[ReviewPackageDetail]:
        entry = self.queue.get(content_id)
        return entry.detail if entry else None

    # ── 页 3：产线日报（mock 视图）────────────────────────────────
    def daily_report_page(self) -> Dict[str, Any]:
        """产线日报 mock：队列态分布 + 前台提示统计（W6 会做真实日报）。"""
        notice_counts: Dict[str, int] = {}
        for n in self.notices:
            notice_counts[n.kind] = notice_counts.get(n.kind, 0) + 1
        return {
            "page": "daily_report",
            "queue_total": self.queue.count(),
            "by_state": self.queue.count_by_state(),
            "notice_counts": notice_counts,
        }

    # ── 人审动作（按钮）：仅改内存状态 + 留痕，不写库不发布 ────────
    def action_mark_ready(self, content_id: str, operator: str) -> CandidateReviewState:
        return mark_ready_to_publish(self._require(content_id), operator)

    def action_reject(self, content_id: str, operator: str, reason: str) -> CandidateReviewState:
        return reject_for_revision(self._require(content_id), operator, reason)

    def action_submit_signoff(self, content_id: str, operator: str) -> CandidateReviewState:
        return submit_for_signoff(self._require(content_id), operator)

    # ── 内部 ──
    def _require(self, content_id: str) -> CandidateReviewEntry:
        e = self.queue.get(content_id)
        if e is None:
            raise KeyError(f"候选不存在：{content_id}")
        return e

    @staticmethod
    def _row(e: CandidateReviewEntry) -> Dict[str, Any]:
        return {
            "content_id": e.content_id,
            "state": e.state.value,
            "must_sign": e.must_sign,
            "notice": e.detail.frontdesk_notice if e.detail else None,
            "reviewable_versions": len(e.detail.reviewable_versions) if e.detail else 0,
        }
