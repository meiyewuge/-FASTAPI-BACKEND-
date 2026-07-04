"""召回结果结构 — RecallResult / RecallStatus / RecallMetadata。

设计依据：M1 W2 9080 只读召回适配。

四种召回状态：approved / candidate / missing / blocked。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class RecallStatus(str, Enum):
    """召回结果状态。

    approved：素材已通过 9080 审批，可直接用于出稿
    candidate：素材处于候选态，需进一步确认
    missing：未召回到任何素材 → 触发缺料报告
    blocked：素材被黑名单/合规规则拦截
    """

    APPROVED = "approved"
    CANDIDATE = "candidate"
    MISSING = "missing"
    BLOCKED = "blocked"


@dataclass
class RecallMetadata:
    """召回元数据。"""

    recall_id: str = field(default_factory=lambda: f"recall_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    query_hash: str = ""
    source_count: int = 0


@dataclass
class RecallResult:
    """9080 召回结果。"""

    materials: List[Dict[str, Any]] = field(default_factory=list)
    status: RecallStatus = RecallStatus.MISSING
    source_refs: List[Any] = field(default_factory=list)    # SourceRef 对象列表
    metadata: RecallMetadata = field(default_factory=RecallMetadata)

    @property
    def is_empty(self) -> bool:
        return len(self.materials) == 0

    @property
    def material_ids(self) -> List[str]:
        return [str(m.get("id", "")) for m in self.materials if m.get("id")]
