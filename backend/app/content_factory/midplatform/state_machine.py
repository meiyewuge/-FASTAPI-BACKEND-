"""candidate_review 状态机 + 人审动作守卫（W5）。

设计依据：M1-W5 条件施工许可 三·状态边界 + 五·必测。

铁律：
- blocked 版本/候选不可备发（必测 4）——BLOCKED 无 → MARKED_READY_TO_PUBLISH 通道；
- needs_human_review / must_sign 必须先经人审/签发，不可直接备发（必测 5/6/14）；
- marked_ready_to_publish 只是"人工备发标记"，不发布、不写库、不 approved（必测 8/9）；
- 人审动作只改内存状态 + 留痕，绝不触发真实后端写库（许可严禁 19）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Set

from .schemas import CandidateReviewEntry, CandidateReviewState


class InvalidReviewAction(ValueError):
    """非法审读动作。"""


# 合法转换表（人审动线）
_ALLOWED: Dict[CandidateReviewState, Set[CandidateReviewState]] = {
    # 入队后由裁决结果自动落位
    CandidateReviewState.PENDING_REVIEW: {
        CandidateReviewState.READY_FOR_REVIEW,
        CandidateReviewState.NEEDS_HUMAN_REVIEW,
        CandidateReviewState.BLOCKED,
    },
    # 六门通过：可备发 或 驳回
    CandidateReviewState.READY_FOR_REVIEW: {
        CandidateReviewState.MARKED_READY_TO_PUBLISH,
        CandidateReviewState.REJECTED_FOR_REVISION,
    },
    # 含 conditional：只能升级为"提交吴哥签发" 或 驳回；不可直接备发（必测 14）
    CandidateReviewState.NEEDS_HUMAN_REVIEW: {
        CandidateReviewState.MUST_SIGN,
        CandidateReviewState.REJECTED_FOR_REVISION,
    },
    # 吴哥签发后：可备发 或 驳回
    CandidateReviewState.MUST_SIGN: {
        CandidateReviewState.MARKED_READY_TO_PUBLISH,
        CandidateReviewState.REJECTED_FOR_REVISION,
    },
    # 门拦截：只能驳回修改，永不备发（必测 4/10）
    CandidateReviewState.BLOCKED: {
        CandidateReviewState.REJECTED_FOR_REVISION,
    },
    # 终态
    CandidateReviewState.MARKED_READY_TO_PUBLISH: set(),
    CandidateReviewState.REJECTED_FOR_REVISION: set(),
}


def _transition(entry: CandidateReviewEntry, target: CandidateReviewState,
                operator: str, note: str = "") -> CandidateReviewState:
    allowed = _ALLOWED.get(entry.state, set())
    if target not in allowed:
        raise InvalidReviewAction(
            f"非法审读动作：{entry.state.value} → {target.value}，"
            f"当前允许：{sorted(s.value for s in allowed)}"
        )
    entry.action_log.append({
        "from": entry.state.value,
        "to": target.value,
        "operator": operator,
        "note": note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    entry.state = target
    return entry.state


# ── 高层人审动作（守卫封装）─────────────────────────────────────────
def mark_ready_to_publish(entry: CandidateReviewEntry, operator: str) -> CandidateReviewState:
    """通过备发：仅 READY_FOR_REVIEW / MUST_SIGN（已签发）可标记。

    注意：这是人工备发标记，不是发布、不写 approved、不入正式库。
    """
    return _transition(entry, CandidateReviewState.MARKED_READY_TO_PUBLISH, operator,
                       note="人工备发标记（≠发布/≠approved）")


def reject_for_revision(entry: CandidateReviewEntry, operator: str, reason: str) -> CandidateReviewState:
    """驳回修改：任何可动状态均可驳回。"""
    return _transition(entry, CandidateReviewState.REJECTED_FOR_REVISION, operator,
                       note=f"驳回修改：{reason}")


def submit_for_signoff(entry: CandidateReviewEntry, operator: str) -> CandidateReviewState:
    """提交吴哥签发：仅 NEEDS_HUMAN_REVIEW 可升级为 MUST_SIGN。"""
    return _transition(entry, CandidateReviewState.MUST_SIGN, operator,
                       note="提交吴哥签发")


def settle_from_review(entry: CandidateReviewEntry, target: CandidateReviewState,
                       operator: str = "system") -> CandidateReviewState:
    """入队后按裁决结果自动落位（PENDING_REVIEW → ready/needs_human/blocked）。"""
    return _transition(entry, target, operator, note="裁决落位")
