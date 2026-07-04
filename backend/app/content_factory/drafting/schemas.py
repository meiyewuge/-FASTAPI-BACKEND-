"""W3 草稿候选数据结构 — draft_candidate + 三版稿。

设计依据：M1-W3 条件施工许可 二.4/二.5/二.6。

三版稿（同一组 used_materials，不得各写各的事实）：
- 专业版（professional）：primary_model 出稿
- 状态美学版（state_aesthetic）：primary + rewrite 润色
- 平台改写版（platform_rewrite）：rewrite_model 平台适配

铁律落到结构上：
- 每一版都绑定同一组 used_materials_ids；
- 每一版都带句级溯源审计（SentenceAudit）；
- 任何一版含"无源事实句" → 该版 blocked，不进候选；
- publish_allowed / writes_approved 为无写入口常量 False（复用 model_router 约束口径）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .sentence_refs import SentenceAudit


class DraftVersionKind(str, Enum):
    """三版稿类型。"""

    PROFESSIONAL = "professional"          # 专业版
    STATE_AESTHETIC = "state_aesthetic"    # 状态美学版
    PLATFORM_REWRITE = "platform_rewrite"  # 平台改写版


class DraftVersionStatus(str, Enum):
    """单版稿状态。"""

    OK = "ok"                              # 通过句级溯源，可进候选
    BLOCKED_UNSOURCED_FACT = "blocked_unsourced_fact"  # 含无源事实句
    BLOCKED_NEW_FACT = "blocked_new_fact"  # 模型新增了 used_materials 之外的事实
    GEN_FAILED = "gen_failed"              # 模型生成失败/缺料，未产出


class DraftCandidateStatus(str, Enum):
    """整份候选稿状态。"""

    DRAFT_CANDIDATE = "draft_candidate"    # 至少一版 OK，停在 W3 候选态
    HALTED_MISSING_MATERIALS = "halted_missing_materials"  # 缺料停单
    BLOCKED = "blocked"                    # 全部版本被拦（无源/新增事实）


@dataclass
class DraftVersion:
    """单版稿。"""

    kind: DraftVersionKind
    text: Optional[str]
    status: DraftVersionStatus
    used_materials_ids: List[str] = field(default_factory=list)
    audit: Optional[SentenceAudit] = None
    produced_by_role: Optional[str] = None
    produced_by_model: Optional[str] = None
    block_reason: Optional[str] = None

    @property
    def is_ok(self) -> bool:
        return self.status == DraftVersionStatus.OK


@dataclass
class DraftCandidate:
    """W3 草稿候选稿 — 三版稿聚合，停在候选态，绝不发布。

    出口约束：publish_allowed / writes_approved 为常量 False，无写入口（init=False）。
    """

    content_id: str
    brief_id: str
    trace_id: str
    status: DraftCandidateStatus
    used_materials_ids: List[str] = field(default_factory=list)
    versions: List[DraftVersion] = field(default_factory=list)
    must_sign: bool = False
    halt_reason: Optional[str] = None
    # ── 常量出口约束，无写入口 ──
    publish_allowed: bool = field(default=False, init=False)
    writes_approved: bool = field(default=False, init=False)

    @property
    def ok_versions(self) -> List[DraftVersion]:
        return [v for v in self.versions if v.is_ok]
