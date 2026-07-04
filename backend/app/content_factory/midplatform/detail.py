"""审读包详情装配（W5）— 从 W4 ReviewPackagePre 构造审读台展示。

设计依据：M1-W5 条件施工许可 二.3/二.5/二.9 + 五·必测 13。

职责：
- 把 ReviewPackagePre 映射为 ReviewPackageDetail（三版稿视图 + 六门 gate_summary）；
- G1/G3 fail 高亮（必测 13）；
- blocked 版本 can_mark_ready=False（必测 4）；
- 按状态生成前台提示（缺料停单/门 blocked/needs_human_review，必测 5/6/12）。
"""
from __future__ import annotations

from typing import Optional

from backend.app.content_factory.gates.review_package import ReviewPackagePre

from .schemas import (
    CandidateReviewState,
    GateSummaryRow,
    ReviewPackageDetail,
    VersionReviewView,
)

# G1/G3 fail 需高亮（合规红线 / 事实引用）
_HIGHLIGHT_GATES = {"G1_compliance", "G3_fact_ref"}

# W4 review_status（str）→ W5 candidate_review 状态
_STATUS_MAP = {
    "ready_for_review": CandidateReviewState.READY_FOR_REVIEW,
    "needs_human_review": CandidateReviewState.NEEDS_HUMAN_REVIEW,
    "needs_revision": CandidateReviewState.NEEDS_HUMAN_REVIEW,  # 部分 fail → 交人工判断
    "blocked": CandidateReviewState.BLOCKED,
}

_NOTICE = {
    CandidateReviewState.NEEDS_HUMAN_REVIEW: "⚠️ 含谨慎项/部分版本未过门，须人工审读后再决定。",
    CandidateReviewState.BLOCKED: "⛔ 六硬门后无可用版本，不可备发，只能驳回修改。",
    CandidateReviewState.READY_FOR_REVIEW: "✅ 六门通过，可审读并标记备发（备发≠发布）。",
}


def map_review_state(review_status: str) -> CandidateReviewState:
    return _STATUS_MAP.get(review_status, CandidateReviewState.PENDING_REVIEW)


def build_review_package_detail(pkg: ReviewPackagePre) -> ReviewPackageDetail:
    """从 W4 ReviewPackagePre 装配审读包详情。"""
    state = map_review_state(pkg.review_status)

    version_views = []
    for slot in pkg.version_slots:
        rows = []
        for gate, verdict in slot.gate_summary.items():
            rows.append(GateSummaryRow(
                gate=gate,
                verdict=verdict,
                highlight=(verdict == "fail" and gate in _HIGHLIGHT_GATES),
            ))
        version_views.append(VersionReviewView(
            version_kind=slot.version_kind,
            text=slot.text,
            used_materials_ids=slot.used_materials_ids,
            loop_status=slot.loop_status,
            is_reviewable=slot.is_reviewable,
            # blocked 候选下，任何版本都不可备发（必测 4）
            can_mark_ready=slot.is_reviewable and state != CandidateReviewState.BLOCKED,
            gate_rows=rows,
        ))

    return ReviewPackageDetail(
        content_id=pkg.content_id,
        brief_id=pkg.brief_id,
        trace_id=pkg.trace_id,
        review_state=state,
        must_sign=pkg.must_sign,
        loop_rounds_used=pkg.loop_rounds_used,
        version_views=version_views,
        frontdesk_notice=_NOTICE.get(state),
    )
