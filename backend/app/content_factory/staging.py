"""content_staging 私有目录 — 内存存储（mock 阶段）。

设计依据：M1 W1 服务骨架。

本层职责边界：
- 内存字典存储 ContentStagingEntry；
- put / get / list_by_brief / list_by_state 四个基本操作；
- 不持久化、不写外部数据库；
- 不暴露给外部路由。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .schemas import ContentStagingEntry, FactoryTaskState


@dataclass
class ContentStaging:
    """content_staging 私有目录内存存储。"""

    _entries: Dict[str, ContentStagingEntry] = field(default_factory=dict)

    def put(self, entry: ContentStagingEntry) -> None:
        """写入或更新条目。"""
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        self._entries[entry.content_id] = entry

    def get(self, content_id: str) -> Optional[ContentStagingEntry]:
        """按 content_id 查询。"""
        return self._entries.get(content_id)

    def list_by_brief(self, brief_id: str) -> List[ContentStagingEntry]:
        """按 brief_id 查询所有关联条目。"""
        return [e for e in self._entries.values() if e.brief_id == brief_id]

    def list_by_state(self, state: FactoryTaskState) -> List[ContentStagingEntry]:
        """按状态筛选。"""
        return [e for e in self._entries.values() if e.state == state]

    def all(self) -> List[ContentStagingEntry]:
        """返回全部条目。"""
        return list(self._entries.values())

    def count(self) -> int:
        """条目总数。"""
        return len(self._entries)
