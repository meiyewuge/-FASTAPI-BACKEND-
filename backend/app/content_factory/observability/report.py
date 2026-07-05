"""每日产线日报生成器 + 异常观测（W6，mock）。

设计依据：M1-W6 条件施工许可 五·指标 + 六·异常观测。

指标口径纪律（严禁 15/16）：
- marked_ready_to_publish_count 是"备发标记数"，不是发布量；
- 日报不产出 published_count / approved_count 任何"发布/入库"口径指标。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from .observer import ProductionLineObserver
from .schemas import AnomalyFlag, AnomalyKind, DailyReport, RunOutcome


@dataclass
class AnomalyThresholds:
    """异常观测阈值（草案，M1 施工/正式观测阶段校准）。"""

    g1_g3_fail_rate: float = 0.30       # G1/G3 fail 高发：占过门运行比例阈值
    human_backlog: int = 5              # 人审积压：needs_human_review + must_sign 阈值
    missing_after_filter_min: int = 1   # 过滤后缺料：达到即提示
    loop_exhausted_min: int = 1         # loop 耗尽：达到即提示


def build_daily_report(
    observer: ProductionLineObserver,
    day: Optional[str] = None,
    thresholds: Optional[AnomalyThresholds] = None,
) -> DailyReport:
    """从观测器聚合每日日报（纯只读计算）。"""
    day = day or datetime.now(timezone.utc).date().isoformat()
    th = thresholds or AnomalyThresholds()
    obs = observer.observations
    by_outcome = observer.count_by_outcome()
    rc = observer.review_state_counts

    # ── 运行观测指标（许可五）──────────────────────────────────────
    metrics = {
        "brief_count": observer.brief_count,
        "run_count": observer.run_count,
        "draft_candidate_count": by_outcome.get(RunOutcome.PACKAGED.value, 0),
        "gate_blocked_count": by_outcome.get(RunOutcome.GATE_BLOCKED.value, 0),
        "draft_blocked_count": by_outcome.get(RunOutcome.BLOCKED_DRAFT.value, 0),
        "missing_materials_count": by_outcome.get(RunOutcome.HALTED_MISSING_MATERIALS.value, 0),
        # 审读态（≠ approved 量）
        "needs_human_review_count": rc.get("needs_human_review", 0) + rc.get("must_sign", 0),
        "marked_ready_to_publish_count": rc.get("marked_ready_to_publish", 0),  # 备发标记数，≠发布量
        "rejected_for_revision_count": rc.get("rejected_for_revision", 0),
    }

    anomalies = _detect_anomalies(observer, metrics, th)

    return DailyReport(
        date=day,
        metrics=metrics,
        by_outcome=by_outcome,
        review_state_counts=dict(rc),
        anomalies=anomalies,
    )


def _detect_anomalies(observer, metrics, th) -> list:
    obs = observer.observations
    flags = []

    # 无 recall_client
    no_client = [o for o in obs if not o.had_recall_client]
    if no_client:
        flags.append(AnomalyFlag(
            AnomalyKind.NO_RECALL_CLIENT, len(no_client),
            "存在未配置召回客户端的运行，直接缺料停单", severity="high"))

    # 黑名单过滤后缺料（有召回客户端但仍缺料停单）
    missing_after = [o for o in obs
                     if o.outcome == RunOutcome.HALTED_MISSING_MATERIALS and o.had_recall_client]
    if len(missing_after) >= th.missing_after_filter_min:
        flags.append(AnomalyFlag(
            AnomalyKind.MISSING_AFTER_FILTER, len(missing_after),
            "召回/黑名单过滤后素材不足导致停单", severity="warning"))

    # G1/G3 fail 高发（占过门运行比例）
    gated = [o for o in obs if o.loop_rounds_used > 0]
    g1g3 = sum(1 for o in gated if o.g1_fail_count or o.g3_fail_count)
    if gated and (g1g3 / len(gated)) >= th.g1_g3_fail_rate:
        flags.append(AnomalyFlag(
            AnomalyKind.HIGH_G1_G3_FAIL, g1g3,
            f"G1/G3 fail 高发：{g1g3}/{len(gated)} 过门运行命中", severity="high"))

    # loop 3 圈耗尽
    exhausted = [o for o in obs if o.loop_rounds_used >= 3 and not o.loop_converged]
    if len(exhausted) >= th.loop_exhausted_min:
        flags.append(AnomalyFlag(
            AnomalyKind.LOOP_EXHAUSTED, len(exhausted),
            "loop 3 圈耗尽仍未收敛", severity="warning"))

    # 人审积压
    backlog = metrics["needs_human_review_count"]
    if backlog >= th.human_backlog:
        flags.append(AnomalyFlag(
            AnomalyKind.HUMAN_REVIEW_BACKLOG, backlog,
            f"人审积压 {backlog} 条（needs_human_review + must_sign）", severity="warning"))

    return flags
