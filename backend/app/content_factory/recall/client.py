"""9080 只读召回客户端 — Protocol + Mock 实现。

设计依据：M1 W2 9080 只读召回适配。

本层职责边界：
- 9080 只读调用（不写 approved / 不 reindex / 不直连 9200）；
- 可配置、可 mock，默认 mock=True；
- 真实接入时经环境变量注入 base_url，本层 mock 阶段不发起 HTTP。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from .results import RecallMetadata, RecallResult, RecallStatus


# ──────────────────────────────────────────────────────────────────────
# 召回查询
# ──────────────────────────────────────────────────────────────────────
@dataclass
class RecallQuery:
    """9080 召回查询参数。"""

    brief_id: str
    keywords: List[str] = field(default_factory=list)
    material_types: Optional[List[str]] = None   # None = 不过滤类型
    max_results: int = 10


# ──────────────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────────────
@dataclass
class RecallConfig:
    """9080 召回配置。默认 mock=True，不发起真实 HTTP。"""

    base_url: str = "mock"
    timeout: float = 10.0
    mock: bool = True      # True = 使用 MockRecallClient，不访问 9080


# ──────────────────────────────────────────────────────────────────────
# 客户端协议
# ──────────────────────────────────────────────────────────────────────
class RecallClient(Protocol):
    """9080 只读召回客户端协议 — 可插拔。"""

    config: RecallConfig

    def recall(self, query: RecallQuery) -> RecallResult:
        """执行召回查询，返回 RecallResult。"""
        ...


# ──────────────────────────────────────────────────────────────────────
# Mock 实现
# ──────────────────────────────────────────────────────────────────────
@dataclass
class MockRecallClient:
    """Mock 召回客户端 — 返回预置脚本数据，不发起真实 HTTP。

    scripted_results：按调用顺序返回；耗尽后返回空结果。
    """

    config: RecallConfig = field(default_factory=RecallConfig)
    scripted_results: List[RecallResult] = field(default_factory=list)
    calls: List[RecallQuery] = field(default_factory=list)

    def recall(self, query: RecallQuery) -> RecallResult:
        self.calls.append(query)

        if self.scripted_results:
            if len(self.scripted_results) > 1:
                return self.scripted_results.pop(0)
            return self.scripted_results[0]

        # 默认空结果
        return RecallResult(
            materials=[],
            status=RecallStatus.MISSING,
            source_refs=[],
            metadata=RecallMetadata(
                recall_id=f"recall_{uuid.uuid4().hex[:12]}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                query_hash=str(hash(tuple(query.keywords))),
                source_count=0,
            ),
        )
