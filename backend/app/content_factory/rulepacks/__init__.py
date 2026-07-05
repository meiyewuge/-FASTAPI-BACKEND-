"""W7 真实规则集契约子包（M1 条件施工 · 骨架阶段）。

设计依据：M1-W7 条件施工许可 二.1-二.4。

本子包为纯契约 + 骨架 mock：
- rulepack 支持外置 / 版本化 / md5 签收；骨架规则 is_mock=True；
- **不把 mock 规则当生产规则**（is_production_ready 需 signed 且 非 mock，严禁 20）；
- G3 正式 FactRefAdjudicator 契约 + Mock 实现（不接真实检测库）；
- G4 四平台结构规则集契约。
"""
from .schemas import Rule, RuleAction, RulePack, RuleSeverity
from .gates import (
    all_gate_rulepacks,
    g1_rulepack, g2_rulepack, g3_rulepack, g4_rulepack, g5_rulepack, g6_rulepack,
)
from .fact_ref_contract import (
    EvidenceType,
    FactClaim,
    FactClaimVerdict,
    FormalFactRefAdjudicator,
    G3AdjudicationResult,
    MockFormalG3Adjudicator,
)
from .platform_contract import VALID_PLATFORMS, PlatformRuleSet, platform_rulesets

__all__ = [
    "EvidenceType",
    "FactClaim",
    "FactClaimVerdict",
    "FormalFactRefAdjudicator",
    "G3AdjudicationResult",
    "MockFormalG3Adjudicator",
    "PlatformRuleSet",
    "Rule",
    "RuleAction",
    "RulePack",
    "RuleSeverity",
    "VALID_PLATFORMS",
    "all_gate_rulepacks",
    "g1_rulepack", "g2_rulepack", "g3_rulepack",
    "g4_rulepack", "g5_rulepack", "g6_rulepack",
    "platform_rulesets",
]
