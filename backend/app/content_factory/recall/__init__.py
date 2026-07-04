"""9080 只读召回子包（M1 W2）。

本包为纯库层代码：
- 9080 只读调用，不写 approved / 不 reindex / 不直连 9200；
- 默认 mock=True，不发起真实 HTTP；
- 白名单 / 黑名单过滤 + used_materials 绑定 + 缺料报告。
"""
from .client import MockRecallClient, RecallClient, RecallConfig, RecallQuery
from .results import RecallMetadata, RecallResult, RecallStatus
from .filters import DEFAULT_BLACKLIST, DEFAULT_WHITELIST, apply_filters, apply_filters_with_report, FilterReport
from .binding import BoundMaterials, bind_materials
from .source_refs import SourceRef, SourceType
from .recall_log import RecallLog, RecallLogEntry, REQUIRED_FIELDS as RECALL_REQUIRED_FIELDS

__all__ = [
    "BoundMaterials",
    "DEFAULT_BLACKLIST",
    "DEFAULT_WHITELIST",
    "FilterReport",
    "MockRecallClient",
    "RecallClient",
    "RecallConfig",
    "RecallLog",
    "RecallLogEntry",
    "RecallMetadata",
    "RecallQuery",
    "RECALL_REQUIRED_FIELDS",
    "RecallResult",
    "RecallStatus",
    "SourceRef",
    "SourceType",
    "apply_filters",
    "apply_filters_with_report",
    "bind_materials",
]
