"""W7 规则集契约 — 可外置 / 可版本化 / 可 md5 签收的 rulepack。

设计依据：M1-W7 条件施工许可 二.1。

这是"契约与骨架"，不是生产规则：
- rulepack 结构支持外置文件加载、版本号、md5 校验、签收元数据；
- 骨架期规则内容沿用 W4 mock 词表作为 v0.1，**明确标注 is_mock=True**；
- 正式法规级规则由后续工单填充并由合规负责人签收（严禁 20：不把 mock 当生产规则）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RuleSeverity(str, Enum):
    HIGH = "high"       # 🔴 红线/高风险
    MEDIUM = "medium"   # 🟡 谨慎
    LOW = "low"         # 🟢 提示


class RuleAction(str, Enum):
    """命中后动作（对齐 W4 GateVerdict）。"""

    FAIL = "fail"
    CONDITIONAL_PASS = "conditional_pass"
    WARNING = "warning"


@dataclass
class Rule:
    """单条规则（外置化最小单元）。"""

    rule_id: str
    description: str
    keywords: List[str] = field(default_factory=list)   # 骨架期以关键词匹配；正式可换正则/模型
    severity: RuleSeverity = RuleSeverity.HIGH
    action: RuleAction = RuleAction.FAIL

    def to_canonical(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "keywords": sorted(self.keywords),
            "severity": self.severity.value,
            "action": self.action.value,
        }


@dataclass
class RulePack:
    """一套外置规则集（对应一个门 scope）。

    md5 / signed_by / signed_at 为签收元数据：
    - md5 由 compute_md5() 对规则规范序列化算出；
    - 未签收（signed_by 空）的 rulepack 不得作为生产规则（is_signed=False）。
    """

    rulepack_id: str
    version: str
    scope: str                       # G1_compliance ... / platform:xiaohongshu ...
    rules: List[Rule] = field(default_factory=list)
    changelog: List[str] = field(default_factory=list)
    md5: str = ""
    signed_by: Optional[str] = None
    signed_at: Optional[str] = None
    is_mock: bool = True             # 骨架期恒 True；正式规则填充后置 False

    # ── md5 签收 ────────────────────────────────────────────────
    def compute_md5(self) -> str:
        """对 (rulepack_id, version, scope, rules) 规范序列化算 md5。"""
        payload = {
            "rulepack_id": self.rulepack_id,
            "version": self.version,
            "scope": self.scope,
            "rules": [r.to_canonical() for r in self.rules],
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.md5(blob.encode("utf-8")).hexdigest()

    def seal(self) -> str:
        """回填 md5（内容定稿后调用）。"""
        self.md5 = self.compute_md5()
        return self.md5

    def verify_md5(self) -> bool:
        """校验 md5 与当前内容一致（防篡改）。"""
        return bool(self.md5) and self.md5 == self.compute_md5()

    def sign(self, signed_by: str, signed_at: str) -> None:
        """签收：先封 md5，再记录签收人/时间。"""
        self.seal()
        self.signed_by = signed_by
        self.signed_at = signed_at

    @property
    def is_signed(self) -> bool:
        return bool(self.signed_by) and self.verify_md5()

    @property
    def is_production_ready(self) -> bool:
        """生产可用 = 已签收 且 非 mock（严禁 20 的结构化守卫）。"""
        return self.is_signed and not self.is_mock
