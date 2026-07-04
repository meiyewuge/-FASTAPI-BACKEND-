"""source_refs 溯源结构 — 素材来源追踪。

设计依据：M1 W2 9080 只读召回适配。

每条召回素材必须附带 SourceRef，记录来源类型、版本、召回时间。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SourceType(str, Enum):
    """素材来源类型。"""

    APPROVED_9080 = "9080_approved"     # 9080 已审批素材
    COMPLIANCE_LIB = "compliance_lib"   # 合规库
    STYLE_LIB = "style_lib"             # 风格库
    ENGINE_ASSET = "engine_asset"       # 东方状态美学引擎素材


@dataclass
class SourceRef:
    """单条素材的来源溯源。"""

    material_id: str
    source_type: SourceType = SourceType.APPROVED_9080
    source_version: str = "v1"
    recalled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
