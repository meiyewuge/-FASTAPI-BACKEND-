"""审读包前置数据结构（W4 · W5 前置）。

设计依据：M1-W4 条件施工许可 二.9。

这是"审读包前置结构"——把候选裁决结果整理成 W5 审读台可直接消费的骨架，
本工单只定结构与装配，不做前台渲染、不做人审动线（那是 W5）。

铁律：publish_allowed / writes_approved 无写入口常量 False；
conditional_pass / needs_human_review 一律 must_sign，不得自动发布。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from backend.app.content_factory.drafting.schemas import DraftCandidate

from .schemas import (
    CandidateGateReport,
    CandidateReviewStatus,
    GateName,
    VersionGateReport,
)


@dataclass
class VersionReviewSlot:
    """审读台单版稿槽位（前置）。"""

    version_kind: str
    text: Optional[str]
    used_materials_ids: List[str]
    gate_summary: dict                      # gate → verdict 摘要
    loop_status: str
    is_reviewable: bool                     # 无 fail 才可进人审


@dataclass
class ReviewPackagePre:
    """审读包前置。W5 在此之上加平台模板/人审动线。

    出口约束：publish_allowed / writes_approved 无写入口常量 False。
    """

    content_id: str
    brief_id: str
    trace_id: str
    review_status: str
    must_sign: bool
    loop_rounds_used: int
    version_slots: List[VersionReviewSlot] = field(default_factory=list)
    # ── 常量出口约束，无写入口 ──
    publish_allowed: bool = field(default=False, init=False)
    writes_approved: bool = field(default=False, init=False)


def _gate_summary(vr: VersionGateReport) -> dict:
    return {r.gate.value: r.verdict.value for r in vr.results}


def build_review_package_pre(
    candidate: DraftCandidate, report: CandidateGateReport
) -> ReviewPackagePre:
    """把候选裁决结果装配成审读包前置。"""
    # 版稿文本按 kind 对齐
    text_by_kind = {v.kind.value: v.text for v in candidate.versions}
    ids_by_kind = {v.kind.value: v.used_materials_ids for v in candidate.versions}

    slots: List[VersionReviewSlot] = []
    for vr in report.version_reports:
        slots.append(VersionReviewSlot(
            version_kind=vr.version_kind,
            text=text_by_kind.get(vr.version_kind),
            used_materials_ids=ids_by_kind.get(vr.version_kind, []),
            gate_summary=_gate_summary(vr),
            loop_status=vr.loop_status.value,
            is_reviewable=not vr.has_fail,
        ))

    return ReviewPackagePre(
        content_id=report.content_id,
        brief_id=report.brief_id,
        trace_id=report.trace_id,
        review_status=report.review_status.value,
        # conditional/needs_human_review 强制 must_sign
        must_sign=report.must_sign or report.review_status == CandidateReviewStatus.NEEDS_HUMAN_REVIEW,
        loop_rounds_used=report.loop_result.rounds_used,
        version_slots=slots,
    )
