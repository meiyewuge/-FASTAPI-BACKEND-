"""SearchRequest 数据类。

字段：query / task_type / max_results / time_range /
      include_domains / exclude_domains / need_ai_summary /
      need_extract / language_hint
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskType(str, Enum):
    """搜索任务类型，决定路由到哪些 provider。

    使用蛇形命名（snake_case），与归档标准一致。
    """
    CHINESE_INDUSTRY_NEWS = "chinese_industry_news"
    GLOBAL_AI_TOOLS = "global_ai_tools"
    OFFICIAL_DOCS = "official_docs"
    TECHNICAL_RESEARCH = "technical_research"
    FALLBACK_LIGHT_SEARCH = "fallback_light_search"


class TimeRange(str, Enum):
    """搜索时间范围。"""
    ONE_DAY = "oneDay"
    ONE_WEEK = "oneWeek"
    ONE_MONTH = "oneMonth"
    ONE_YEAR = "oneYear"


@dataclass
class SearchRequest:
    """统一搜索请求。

    Attributes:
        query: 搜索关键词
        task_type: 任务类型，决定路由策略
        max_results: 最大结果数（上限 20）
        time_range: 时间范围过滤
        include_domains: 仅包含的域名列表
        exclude_domains: 排除的域名列表
        need_ai_summary: 是否需要 AI 摘要
        need_extract: 是否需要正文提取
        language_hint: 语言提示（zh / en / mixed）
    """
    query: str
    task_type: TaskType = TaskType.FALLBACK_LIGHT_SEARCH
    max_results: int = 10
    time_range: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    need_ai_summary: bool = False
    need_extract: bool = False
    language_hint: str = "zh"

    def __post_init__(self) -> None:
        """构造后校验。"""
        # max_results 上限 20
        if self.max_results > 20:
            self.max_results = 20
        if self.max_results < 1:
            self.max_results = 1

        # query 不能为空
        if not self.query or not self.query.strip():
            raise ValueError("query 不能为空")

    def to_dict(self) -> dict:
        """输出 dict。"""
        return {
            "query": self.query,
            "task_type": self.task_type.value if hasattr(self.task_type, "value") else str(self.task_type),
            "max_results": self.max_results,
            "time_range": self.time_range,
            "include_domains": list(self.include_domains),
            "exclude_domains": list(self.exclude_domains),
            "need_ai_summary": self.need_ai_summary,
            "need_extract": self.need_extract,
            "language_hint": self.language_hint,
        }
