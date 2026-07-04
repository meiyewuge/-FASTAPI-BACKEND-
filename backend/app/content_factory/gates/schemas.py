"""W4 六硬门数据结构 — GateResult / GateReport / LoopResult / 候选裁决状态。

设计依据：M1-W4 条件施工许可 一/二/三。

层次：
- 单门 → GateResult（四类判定：pass/fail/conditional_pass/warning）
- 单版稿六门 → VersionGateReport（聚合一版稿的 G1-G6）
- 三版稿 + loop → CandidateGateReport（候选裁决层最终结论）
- loop 编排 → LoopResult（≤3 圈）

铁律落到结构上：
- conditional_pass 只能进人工审读，绝不自动发布；
- publish_allowed / writes_approved 为无写入口常量 False。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class GateName(str, Enum):
    """六硬门（V1.2.1 口径）。"""

    G1_COMPLIANCE = "G1_compliance"          # 合规红线：医疗/功效/绝对化/禁用词
    G2_STATE_BOUNDARY = "G2_state_boundary"  # 状态越界：东方状态美学越界/玄学/转运承诺
    G3_FACT_REF = "G3_fact_ref"              # 事实引用：source_refs/句级溯源/检测完整性
    G4_PLATFORM_STRUCTURE = "G4_platform_structure"  # 平台结构：四出口结构规则
    G5_BRAND_CONSISTENCY = "G5_brand_consistency"    # 品牌一致：只围绕达芙荻丽奢华油
    G6_FORMAT_COMPLETE = "G6_format_complete"        # 格式完整：审读包字段/候选态字段


# 六门固定顺序
GATE_ORDER: List[GateName] = [
    GateName.G1_COMPLIANCE,
    GateName.G2_STATE_BOUNDARY,
    GateName.G3_FACT_REF,
    GateName.G4_PLATFORM_STRUCTURE,
    GateName.G5_BRAND_CONSISTENCY,
    GateName.G6_FORMAT_COMPLETE,
]


class GateVerdict(str, Enum):
    """四类判定。"""

    PASS = "pass"
    FAIL = "fail"
    CONDITIONAL_PASS = "conditional_pass"   # 有条件通过 → 必须人工审读，不得自动发布
    WARNING = "warning"                     # 提示，不阻断


class VersionLoopStatus(str, Enum):
    """单版稿在 loop 中的状态（二.8：needs_revision 位于 loop 层）。"""

    PASS_CLEAN = "pass_clean"          # 无 fail（可含 warning/conditional）
    NEEDS_REVISION = "needs_revision"  # 本圈有 fail，待下一圈重生成（loop 转态）
    BLOCKED = "blocked"                # loop 耗尽仍 fail（含 G1 红线即刻 blocked）


class CandidateReviewStatus(str, Enum):
    """候选裁决层最终结论（二.8）。"""

    READY_FOR_REVIEW = "ready_for_review"        # 至少一版干净通过（可含 warning）
    NEEDS_HUMAN_REVIEW = "needs_human_review"    # 含 conditional_pass → must_sign
    NEEDS_REVISION = "needs_revision"            # 部分版本 fail、部分可用 → 人工修订
    BLOCKED = "blocked"                          # 无任何可用版本（全 fail / G1 红线）


@dataclass
class GateResult:
    """单门判定结果。"""

    gate: GateName
    verdict: GateVerdict
    hits: List[str] = field(default_factory=list)
    note: Optional[str] = None
    # G4 专用：非结构问题不由 G4 裁决，只标注路由到对应门（必测 6）
    routed_to: List[GateName] = field(default_factory=list)

    @property
    def is_fail(self) -> bool:
        return self.verdict == GateVerdict.FAIL


@dataclass
class VersionGateReport:
    """单版稿的六门报告。"""

    version_kind: str
    results: List[GateResult] = field(default_factory=list)
    loop_rounds: int = 1
    loop_status: VersionLoopStatus = VersionLoopStatus.PASS_CLEAN

    @property
    def fails(self) -> List[GateResult]:
        return [r for r in self.results if r.verdict == GateVerdict.FAIL]

    @property
    def conditionals(self) -> List[GateResult]:
        return [r for r in self.results if r.verdict == GateVerdict.CONDITIONAL_PASS]

    @property
    def warnings(self) -> List[GateResult]:
        return [r for r in self.results if r.verdict == GateVerdict.WARNING]

    @property
    def has_fail(self) -> bool:
        return bool(self.fails)

    @property
    def has_g1_redline_fail(self) -> bool:
        return any(r.gate == GateName.G1_COMPLIANCE and r.is_fail for r in self.results)


@dataclass
class LoopResult:
    """loop 编排结果（≤3 圈）。"""

    max_rounds: int = 3
    rounds_used: int = 1
    converged: bool = True
    reason: Optional[str] = None


@dataclass
class CandidateGateReport:
    """候选裁决层最终报告（三版稿聚合）。

    出口约束：publish_allowed / writes_approved 为无写入口常量 False。
    conditional_pass 只能进入人工审读（NEEDS_HUMAN_REVIEW），不得自动发布。
    """

    content_id: str
    brief_id: str
    trace_id: str
    review_status: CandidateReviewStatus
    version_reports: List[VersionGateReport] = field(default_factory=list)
    loop_result: LoopResult = field(default_factory=LoopResult)
    must_sign: bool = False
    # ── 常量出口约束，无写入口 ──
    publish_allowed: bool = field(default=False, init=False)
    writes_approved: bool = field(default=False, init=False)

    @property
    def clean_versions(self) -> List[VersionGateReport]:
        """无 fail 的版本（可进审读）。"""
        return [v for v in self.version_reports if not v.has_fail]
