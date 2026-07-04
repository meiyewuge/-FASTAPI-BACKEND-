"""召回日志 — 14 字段内存记录。

设计依据：M1 W2 9080 只读召回适配。

每次召回（无论成功/失败）必须记录 14 个字段。
M1 mock 阶段为内存实现；持久化属后续工单。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


# 14 个必记字段
REQUIRED_FIELDS = [
    "recall_id", "timestamp", "brief_id", "trace_id",
    "query_keywords", "material_types_requested",
    "materials_returned", "filtered_count",
    "status", "latency_ms", "source_refs_count",
    "whitelist_applied", "blacklist_applied", "error_reason",
]


@dataclass
class RecallLogEntry:
    """单条召回日志记录。"""

    recall_id: str
    timestamp: str
    brief_id: str
    trace_id: str
    query_keywords: List[str]
    material_types_requested: Optional[List[str]]
    materials_returned: int
    filtered_count: int
    status: str
    latency_ms: int
    source_refs_count: int
    whitelist_applied: List[str]
    blacklist_applied: List[str]
    error_reason: Optional[str]


@dataclass
class RecallLog:
    """召回日志内存存储。"""

    entries: List[RecallLogEntry] = field(default_factory=list)

    def record(
        self,
        *,
        brief_id: str,
        trace_id: str,
        query_keywords: List[str],
        material_types_requested: Optional[List[str]],
        materials_returned: int,
        filtered_count: int,
        status: str,
        latency_ms: int = 0,
        source_refs_count: int = 0,
        whitelist_applied: Optional[List[str]] = None,
        blacklist_applied: Optional[List[str]] = None,
        error_reason: Optional[str] = None,
    ) -> RecallLogEntry:
        entry = RecallLogEntry(
            recall_id=f"recall_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            brief_id=brief_id,
            trace_id=trace_id,
            query_keywords=list(query_keywords),
            material_types_requested=material_types_requested,
            materials_returned=materials_returned,
            filtered_count=filtered_count,
            status=status,
            latency_ms=latency_ms,
            source_refs_count=source_refs_count,
            whitelist_applied=whitelist_applied or [],
            blacklist_applied=blacklist_applied or [],
            error_reason=error_reason,
        )
        self.entries.append(entry)
        return entry

    def query_by_brief(self, brief_id: str) -> List[RecallLogEntry]:
        return [e for e in self.entries if e.brief_id == brief_id]

    def query_by_trace(self, trace_id: str) -> List[RecallLogEntry]:
        return [e for e in self.entries if e.trace_id == trace_id]

    def summary(self) -> Dict[str, int]:
        """按 status 统计召回次数。"""
        out: Dict[str, int] = {}
        for e in self.entries:
            out[e.status] = out.get(e.status, 0) + 1
        return out
