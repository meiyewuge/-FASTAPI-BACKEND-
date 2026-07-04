"""W5 审读台数据结构 — candidate_review 状态 / 审读包详情 / 三版稿视图 / 门摘要。

设计依据：M1-W5 条件施工许可 一/二/三。

铁律（许可三 + 四）：
- marked_ready_to_publish 只是"人工备发标记"——不是发布、不是入库、不是 approved；
- candidate_review 不是 approved，不写正式库；
- publish_allowed / writes_approved 无写入口常量 False。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# candidate_review 状态（许可三·状态边界，7 态）
# ──────────────────────────────────────────────────────────────────────
class CandidateReviewState(str, Enum):
    """审读台候选状态。

    入队：pending_review
    裁决态映射：ready_for_review / needs_human_review / blocked
    人审动作态：must_sign / rejected_for_revision / marked_ready_to_publish
    """

    PENDING_REVIEW = "pending_review"                # 刚入队，未展开
    READY_FOR_REVIEW = "ready_for_review"            # 六门通过，可审可备发
    NEEDS_HUMAN_REVIEW = "needs_human_review"         # 含 conditional，须人工判断
    MUST_SIGN = "must_sign"                          # 须提交吴哥签发
    BLOCKED = "blocked"                              # 门拦截，不可备发
    REJECTED_FOR_REVISION = "rejected_for_revision"  # 人工驳回修改
    MARKED_READY_TO_PUBLISH = "marked_ready_to_publish"  # 人工备发标记（≠发布/≠approved）


# ──────────────────────────────────────────────────────────────────────
# 单门展示（六门 gate_summary）
# ──────────────────────────────────────────────────────────────────────
@dataclass
class GateSummaryRow:
    """审读台单门展示行。"""

    gate: str            # G1_compliance ...
    verdict: str         # pass/fail/conditional_pass/warning
    highlight: bool      # G1/G3 fail 高亮（必测 13）
    hits: List[str] = field(default_factory=list)
    note: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# 三版稿审读视图
# ──────────────────────────────────────────────────────────────────────
@dataclass
class VersionReviewView:
    """单版稿在审读台的展示视图。"""

    version_kind: str
    text: Optional[str]
    used_materials_ids: List[str]
    loop_status: str
    is_reviewable: bool                     # 无 fail 才可进人审
    can_mark_ready: bool                    # blocked 版本不可备发（必测 4）
    gate_rows: List[GateSummaryRow] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# 审读包详情
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ReviewPackageDetail:
    """审读包详情（三版稿视图 + 六门摘要 + 状态提示）。

    出口约束：publish_allowed / writes_approved 无写入口常量 False。
    """

    content_id: str
    brief_id: str
    trace_id: str
    review_state: CandidateReviewState
    must_sign: bool
    loop_rounds_used: int
    version_views: List[VersionReviewView] = field(default_factory=list)
    # 前台提示（许可二.9）：缺料停单/门 blocked/needs_human_review
    frontdesk_notice: Optional[str] = None
    # ── 常量出口约束，无写入口 ──
    publish_allowed: bool = field(default=False, init=False)
    writes_approved: bool = field(default=False, init=False)

    @property
    def reviewable_versions(self) -> List[VersionReviewView]:
        return [v for v in self.version_views if v.is_reviewable]


# ──────────────────────────────────────────────────────────────────────
# candidate_review 队列条目
# ──────────────────────────────────────────────────────────────────────
@dataclass
class CandidateReviewEntry:
    """候选审读队列条目（内存，mock；不写正式库）。"""

    content_id: str
    brief_id: str
    trace_id: str
    state: CandidateReviewState
    must_sign: bool
    platform: Optional[str] = None
    detail: Optional[ReviewPackageDetail] = None
    # 人审动作留痕（谁在什么时候做了什么，仅内存）
    action_log: List[Dict[str, str]] = field(default_factory=list)
