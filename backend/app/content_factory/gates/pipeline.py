"""W4 六硬门编排 + ≤3 圈 Loop 控制器。

设计依据：M1-W4 条件施工许可 一/二·6/五。

编排：对 DraftCandidate 的每一版稿逐版执行 G1→G6；
Loop：一版稿若有 fail，最多重生成 3 圈（mock：需注入 revise_callback，
      默认无回调 → 首圈 fail 即耗尽 → blocked）；G1 红线 fail 即刻 blocked，不重试。
聚合：三版稿结论 → CandidateReviewStatus。

严禁（许可）：
- conditional_pass 只进人工审读，绝不自动发布（必测 9）；
- 不把 W3 启发式当正式 G3（G3 走注入的 FactRefAdjudicator）；
- G4 不裁决非结构问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.app.content_factory.drafting.schemas import (
    DraftCandidate,
    DraftVersion,
    DraftVersionStatus,
)

from .fact_ref import FactRefAdjudicator, MockG3Adjudicator
from .rules import GateContext, gate_g1, gate_g2, gate_g4, gate_g5, gate_g6
from .schemas import (
    CandidateGateReport,
    CandidateReviewStatus,
    GateResult,
    LoopResult,
    VersionGateReport,
    VersionLoopStatus,
)

# 一版稿重生成回调：给定当前版稿 + 本圈报告 → 返回改稿后的版稿（mock 注入用）
ReviseCallback = Callable[[DraftVersion, VersionGateReport], DraftVersion]

MAX_LOOP_ROUNDS = 3


@dataclass
class GatePipeline:
    """六硬门流水线 + Loop 控制器。

    fact_adjudicator：G3 正式裁决接口（默认 mock，可换正式规则）。
    revise_callback：loop 重生成回调（默认 None → 单圈定生死）。
    max_rounds：loop 上限（默认 3）。
    """

    fact_adjudicator: FactRefAdjudicator = field(default_factory=MockG3Adjudicator)
    revise_callback: Optional[ReviseCallback] = None
    max_rounds: int = MAX_LOOP_ROUNDS

    # ── 单版稿一圈六门 ─────────────────────────────────────────────
    def _run_gates_once(
        self,
        version: DraftVersion,
        platform: Optional[str],
        line: Optional[str],
        g3_materials: List[Dict[str, Any]],
    ) -> VersionGateReport:
        ctx = GateContext(
            version_kind=version.kind.value,
            text=version.text or "",
            used_materials=g3_materials,
            used_materials_ids=version.used_materials_ids,
            platform=platform,
            line=line,
            has_audit=version.audit is not None,
        )
        results: List[GateResult] = [
            gate_g1(ctx),
            gate_g2(ctx),
            self.fact_adjudicator.adjudicate(ctx.text, g3_materials),  # G3 正式裁决接口
            gate_g4(ctx),
            gate_g5(ctx),
            gate_g6(ctx),
        ]
        return VersionGateReport(version_kind=version.kind.value, results=results)

    # ── 单版稿 loop（≤3 圈）────────────────────────────────────────
    def _run_version_loop(
        self,
        version: DraftVersion,
        platform: Optional[str],
        line: Optional[str],
        g3_materials: List[Dict[str, Any]],
    ) -> VersionGateReport:
        current = version
        rounds = 1
        report = self._run_gates_once(current, platform, line, g3_materials)

        while report.has_fail:
            # G1 红线 fail：即刻 blocked，不重试（不浪费 loop 圈数）
            if report.has_g1_redline_fail:
                report.loop_status = VersionLoopStatus.BLOCKED
                report.loop_rounds = rounds
                return report
            # loop 耗尽 或 无重生成回调 → blocked（必测 11：3 圈仍 fail → blocked）
            if rounds >= self.max_rounds or self.revise_callback is None:
                report.loop_status = VersionLoopStatus.BLOCKED
                report.loop_rounds = rounds
                return report
            # 本圈需修订 → 重生成后进入下一圈
            report.loop_status = VersionLoopStatus.NEEDS_REVISION
            current = self.revise_callback(current, report)
            rounds += 1
            report = self._run_gates_once(current, platform, line, g3_materials)

        report.loop_status = VersionLoopStatus.PASS_CLEAN
        report.loop_rounds = rounds
        return report

    # ── 候选裁决（三版稿聚合）──────────────────────────────────────
    def run(
        self,
        candidate: DraftCandidate,
        platform: Optional[str] = None,
        line: Optional[str] = None,
        g3_materials: Optional[List[Dict[str, Any]]] = None,
    ) -> CandidateGateReport:
        mats = g3_materials or []
        version_reports: List[VersionGateReport] = []
        max_rounds_used = 1
        for v in candidate.versions:
            # 只对成功出稿的版本过门；W3 已 blocked 的版本直接记 blocked
            if v.status != DraftVersionStatus.OK:
                version_reports.append(VersionGateReport(
                    version_kind=v.kind.value,
                    loop_status=VersionLoopStatus.BLOCKED,
                ))
                continue
            vr = self._run_version_loop(v, platform, line, mats)
            version_reports.append(vr)
            max_rounds_used = max(max_rounds_used, vr.loop_rounds)

        review_status, must_sign = self._aggregate(version_reports)
        converged = review_status != CandidateReviewStatus.BLOCKED
        return CandidateGateReport(
            content_id=candidate.content_id,
            brief_id=candidate.brief_id,
            trace_id=candidate.trace_id,
            review_status=review_status,
            version_reports=version_reports,
            loop_result=LoopResult(
                max_rounds=self.max_rounds,
                rounds_used=max_rounds_used,
                converged=converged,
                reason=review_status.value,
            ),
            must_sign=must_sign,
        )

    @staticmethod
    def _aggregate(reports: List[VersionGateReport]) -> tuple:
        """三版稿 → 候选裁决状态 + must_sign。

        - 无任何"无 fail"版本 → BLOCKED（必测 11：3 圈仍 fail → blocked）
        - 部分版本 fail、部分可用 → NEEDS_REVISION
        - 全可用且含 conditional_pass → NEEDS_HUMAN_REVIEW（must_sign，必测 13）
        - 全可用仅 warning/pass → READY_FOR_REVIEW（必测 12）
        """
        clean = [r for r in reports if not r.has_fail]
        failed = [r for r in reports if r.has_fail]

        if not clean:
            return CandidateReviewStatus.BLOCKED, False
        if failed:
            return CandidateReviewStatus.NEEDS_REVISION, False
        if any(r.conditionals for r in clean):
            return CandidateReviewStatus.NEEDS_HUMAN_REVIEW, True
        return CandidateReviewStatus.READY_FOR_REVIEW, False
