"""W4 六硬门编排与候选裁决子包（M1 条件施工 · 骨架阶段）。

设计依据：M1-W4 条件施工许可。

本子包为纯库层：
- 只对 W3 DraftCandidate 做质检编排，不接真实模型/真实 9080/FastAPI；
- G3 走正式裁决接口 FactRefAdjudicator（不把 W3 启发式当正式 G3）；
- G4 只判平台结构，非结构问题路由到 G1/G2/G3/G5；
- conditional_pass 只进人工审读，publish_allowed/writes_approved 无写入口常量 False；
- 不进 W5（审读包前置结构就位，不做前台/人审动线）。

模块：
- schemas.py：GateResult/VersionGateReport/CandidateGateReport/LoopResult/裁决状态枚举
- fact_ref.py：G3 正式裁决接口 + Mock 实现
- rules.py：G1/G2/G4/G5/G6 门规则（mock）+ GateContext
- pipeline.py：GatePipeline（六门编排 + ≤3 圈 Loop）
- review_package.py：审读包前置结构（W5 前置）
"""
from .schemas import (
    GATE_ORDER,
    CandidateGateReport,
    CandidateReviewStatus,
    GateName,
    GateResult,
    GateVerdict,
    LoopResult,
    VersionGateReport,
    VersionLoopStatus,
)
from .rules import (
    GateContext,
    gate_g1,
    gate_g2,
    gate_g4,
    gate_g5,
    gate_g6,
)
from .fact_ref import FactRefAdjudicator, MockG3Adjudicator
from .pipeline import GatePipeline, ReviseCallback, MAX_LOOP_ROUNDS
from .review_package import ReviewPackagePre, VersionReviewSlot, build_review_package_pre

__all__ = [
    "GATE_ORDER",
    "CandidateGateReport",
    "CandidateReviewStatus",
    "FactRefAdjudicator",
    "GateContext",
    "GateName",
    "GatePipeline",
    "GateResult",
    "GateVerdict",
    "LoopResult",
    "MAX_LOOP_ROUNDS",
    "MockG3Adjudicator",
    "ReviewPackagePre",
    "ReviseCallback",
    "VersionGateReport",
    "VersionLoopStatus",
    "VersionReviewSlot",
    "build_review_package_pre",
    "gate_g1",
    "gate_g2",
    "gate_g4",
    "gate_g5",
    "gate_g6",
]
