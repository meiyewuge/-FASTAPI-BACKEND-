"""IndustryIntelligenceCard — 产业情报卡（17 核心字段 + 9 扩展字段）。

基于《美丽大健康全球产业链数据采集与入库标准 V0.1.1》。
迁移自 V0.1.3 Mock industry_card_schema.py，口径完全一致。

铁律:
- candidate_for_ingest 默认 True
- ingest_status 默认 "pending"，禁止 "formal"
- provider 不进 17 核心字段，进 provider_metadata
- cost 信息进 cost_metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# 允许的 ingest_status 值（formal 禁止）
ALLOWED_INGEST_STATUSES = {"pending", "review", "approved", "rejected"}
FORBIDDEN_INGEST_STATUS = "formal"


@dataclass
class IndustryIntelligenceCard:
    """产业情报卡 — 17 核心字段 + 9 扩展字段。"""

    # ── 17 核心字段 ───────────────────────────────────
    # 1
    title: str = ""
    # 2
    url: str = ""
    # 3
    publish_time: str = ""
    # 4
    summary: str = ""
    # 5
    source: str = ""
    # 6
    fetched_at: str = ""
    # 7
    country_or_region: str = "中国"
    # 8
    industry_dimension: str = ""           # 一级维度
    # 9
    subtags: list[str] = field(default_factory=list)  # 二级标签（多标签）
    # 10
    business_relevance: str = ""
    # 11
    applicable_scenario: str = ""
    # 12
    confidence_score: float = 0.0
    # 13
    freshness_score: float = 0.0
    # 14
    risk_notes: str = ""
    # 15
    risk_category: str = "normal"
    # 16
    knowledge_type: str = "trend"
    # 17
    evidence_excerpt: str = ""

    # ── 9 扩展字段 ───────────────────────────────────
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    cost_metadata: dict[str, Any] = field(default_factory=dict)
    relevance_score: float = float("nan")
    source_credibility_score: float = float("nan")
    final_score: float = float("nan")
    computation_trace: dict[str, Any] = field(default_factory=dict)
    suggested_action: str = ""
    candidate_for_ingest: bool = True
    ingest_status: str = "pending"
    ingest_reason: str = "外部搜索结果默认进入待审候选池"
    original_search_query: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """构造后校验：ingest_status 禁止 formal。"""
        if self.ingest_status == FORBIDDEN_INGEST_STATUS:
            raise ValueError(
                f"ingest_status 禁止为 '{FORBIDDEN_INGEST_STATUS}'，"
                f"外部搜索结果不允许直接入库为正式记录"
            )
        if self.ingest_status not in ALLOWED_INGEST_STATUSES:
            raise ValueError(
                f"ingest_status '{self.ingest_status}' 不在允许列表: {ALLOWED_INGEST_STATUSES}"
            )

    def to_dict(self) -> dict:
        """输出 dict。"""
        return {
            # 17 核心字段
            "title": self.title,
            "url": self.url,
            "publish_time": self.publish_time,
            "summary": self.summary,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "country_or_region": self.country_or_region,
            "industry_dimension": self.industry_dimension,
            "subtags": list(self.subtags),
            "business_relevance": self.business_relevance,
            "applicable_scenario": self.applicable_scenario,
            "confidence_score": round(self.confidence_score, 3),
            "freshness_score": round(self.freshness_score, 3),
            "risk_notes": self.risk_notes,
            "risk_category": self.risk_category,
            "knowledge_type": self.knowledge_type,
            "evidence_excerpt": self.evidence_excerpt,
            # 9 扩展字段
            "provider_metadata": dict(self.provider_metadata),
            "cost_metadata": dict(self.cost_metadata),
            "relevance_score": round(self.relevance_score, 3),
            "suggested_action": self.suggested_action,
            "candidate_for_ingest": self.candidate_for_ingest,
            "ingest_status": self.ingest_status,
            "ingest_reason": self.ingest_reason,
            "original_search_query": self.original_search_query,
            "tags": list(self.tags),
        }

    @staticmethod
    def core_field_names() -> list[str]:
        """17 核心字段名列表。"""
        return [
            "title", "url", "publish_time", "summary", "source",
            "fetched_at", "country_or_region", "industry_dimension",
            "subtags", "business_relevance", "applicable_scenario",
            "confidence_score", "freshness_score", "risk_notes",
            "risk_category", "knowledge_type", "evidence_excerpt",
        ]

    @staticmethod
    def extension_field_names() -> list[str]:
        """9 扩展字段名列表。"""
        return [
            "provider_metadata", "cost_metadata", "relevance_score",
            "suggested_action", "candidate_for_ingest", "ingest_status",
            "ingest_reason", "original_search_query", "tags",
        ]
