"""G3 正式 FactRefAdjudicator 契约（W7）。

设计依据：M1-W7 条件施工许可 二.3。

这是 W4 MockG3Adjudicator 的**正式契约升级**：把"事实句 → 证据"的裁决拆成
结构化字段，供正式法规级规则实现。骨架期提供 Mock 实现，**不接真实检测库**。

fail_closed 铁律：任一事实主张的证据缺失/无法判定 → fail（不放行）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol


class EvidenceType(str, Enum):
    DETECTION_REPORT = "detection_report"    # 检测报告
    APPROVED_MATERIAL = "approved_material"  # 9080 approved 素材
    REGULATION = "regulation"                # 法规依据
    NONE = "none"                            # 无证据


@dataclass
class FactClaim:
    """一条事实主张的结构化裁决单元（G3 正式契约核心）。"""

    fact_claim: str                              # 事实句原文
    source_ref: Optional[str] = None             # 溯源素材 ID
    evidence_type: EvidenceType = EvidenceType.NONE
    detection_method: Optional[str] = None       # 检测方法（体外/人体）
    report_no: Optional[str] = None              # 报告编号
    institution: Optional[str] = None            # 检测机构
    body_or_in_vitro: Optional[str] = None       # 体内/体外标注
    missing_evidence_reason: Optional[str] = None
    fail_closed: bool = True                     # 证据不全即拒（恒 True）

    @property
    def is_detection_claim(self) -> bool:
        return self.evidence_type == EvidenceType.DETECTION_REPORT

    def evaluate(self) -> "FactClaimVerdict":
        """fail_closed 裁决：无源 / 检测三要素不全 → fail。"""
        # 无 source_ref → 无源事实句
        if not self.source_ref:
            return FactClaimVerdict(self, passed=False, reason="无 source_ref（无源事实句）")
        # 检测宣称须三要素齐备
        if self.is_detection_claim:
            missing = []
            if not (self.detection_method or self.body_or_in_vitro):
                missing.append("检测方法")
            if not self.report_no:
                missing.append("报告编号")
            if not self.institution:
                missing.append("检测机构")
            if missing:
                return FactClaimVerdict(self, passed=False,
                                        reason="检测三要素缺失：" + "、".join(missing))
        return FactClaimVerdict(self, passed=True, reason="证据齐备")


@dataclass
class FactClaimVerdict:
    claim: FactClaim
    passed: bool
    reason: str


@dataclass
class G3AdjudicationResult:
    """一份稿件的 G3 正式裁决结果。"""

    passed: bool
    claim_verdicts: List[FactClaimVerdict] = field(default_factory=list)

    @property
    def violations(self) -> List[str]:
        return [v.claim.fact_claim for v in self.claim_verdicts if not v.passed]


class FormalFactRefAdjudicator(Protocol):
    """G3 正式裁决契约。真实法规级规则实现本 Protocol 后注入 W4 pipeline。"""

    def adjudicate_claims(self, claims: List[FactClaim]) -> G3AdjudicationResult:
        ...


@dataclass
class MockFormalG3Adjudicator:
    """骨架期正式契约实现（fail_closed 逐条裁决）。不接真实检测库。"""

    is_mock: bool = True

    def adjudicate_claims(self, claims: List[FactClaim]) -> G3AdjudicationResult:
        verdicts = [c.evaluate() for c in claims]
        return G3AdjudicationResult(
            passed=all(v.passed for v in verdicts),
            claim_verdicts=verdicts,
        )
