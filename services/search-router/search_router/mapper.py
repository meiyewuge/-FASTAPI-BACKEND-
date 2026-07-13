"""SearchResultMapper — SearchResult → IndustryIntelligenceCard 字段映射。

17 核心字段 + 9 扩展字段完整映射。
LLM 增强字段先填默认值或规则推断，T4 再增强。
必填字段缺失时拒绝映射或返回明确错误。
high-risk 字段不自动转门店建议。
"""

from __future__ import annotations

from datetime import datetime
import copy
from typing import Any

from search_router.industry.industry_mapper import (
    infer_industry_dimension,
    infer_sub_tags,
    infer_risk_category,
    infer_business_relevance,
    infer_applicable_scenario,
    build_risk_notes,
    build_suggested_action,
    is_legal_policy_official_source,
)
from search_router.industry.industry_taxonomy import validate_sub_tags
from search_router.industry.knowledge_type_mapper import infer_knowledge_type
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.models.search_request import TaskType
from search_router.models.search_response import SearchResult


class MapperError(Exception):
    """映射错误。"""
    pass


# 必填字段（缺失则拒绝映射）
REQUIRED_FIELDS = ["title", "url"]


def map_search_result_to_card(
    result: SearchResult,
    task_type: str = "",
    query: str = "",
    estimated_cost: float = 0.0,
    merged_from: list[str] | None = None,
) -> IndustryIntelligenceCard:
    """将 SearchResult 映射为 IndustryIntelligenceCard。

    Args:
        result: 搜索结果
        task_type: 任务类型
        query: 原始搜索查询
        estimated_cost: 预估成本
        merged_from: 合并来源 provider 列表

    Returns:
        IndustryIntelligenceCard

    Raises:
        MapperError: 必填字段缺失时拒绝映射
    """
    # 必填字段校验
    missing: list[str] = []
    if not result.title or not result.title.strip():
        missing.append("title")
    if not result.url or not result.url.strip():
        missing.append("url")
    if missing:
        raise MapperError(f"必填字段缺失: {missing}，拒绝映射")

    # 推断产业字段
    search_query = query or result.title
    dimension = infer_industry_dimension(search_query, task_type)
    sub_tags = infer_sub_tags(dimension, search_query)
    knowledge_type = infer_knowledge_type(search_query, task_type)
    risk_category = infer_risk_category(search_query, knowledge_type)

    # legal_policy 官方来源检查
    if risk_category == "legal_policy" and not is_legal_policy_official_source(result.url):
        risk_notes = "法规政策类内容：建议优先引用官方来源（.gov.cn），当前来源非官方"
    else:
        risk_notes = build_risk_notes(risk_category, knowledge_type)

    # 构建 provider_metadata
    provider_meta: dict[str, Any] = {
        "provider": result.provider,
        "raw": {
            "title": result.title,
            "url": result.url,
            "summary": result.summary,
            "source": result.source,
        },
    }
    if merged_from:
        provider_meta["merged_from"] = list(merged_from)
    elif result.raw.get("merged_from"):
        provider_meta["merged_from"] = list(result.raw.get("merged_from", []))

    # 构建 cost_metadata
    cost_meta: dict[str, Any] = {
        "estimated_cost": round(estimated_cost, 4),
        "credits_used": getattr(result, "credits_used", 0),
    }

    # 构建建议动作
    suggested_action = build_suggested_action(risk_category, result.confidence_score)

    # 适用场景
    applicable_scenario = infer_applicable_scenario(risk_category, knowledge_type)

    # 业务相关度
    business_relevance = infer_business_relevance(dimension, knowledge_type)

    # fetched_at 自动生成
    from datetime import timezone
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    card = IndustryIntelligenceCard(
        # 17 核心字段
        title=result.title,
        url=result.url,
        publish_time=result.publish_time or "",
        summary=result.summary or "",
        source=result.source or "",
        fetched_at=fetched_at,
        country_or_region="中国",
        industry_dimension=dimension,
        subtags=list(sub_tags),
        business_relevance=business_relevance,
        applicable_scenario=applicable_scenario,
        confidence_score=result.confidence_score,
        freshness_score=result.freshness_score,
        risk_notes=risk_notes,
        risk_category=risk_category,
        knowledge_type=knowledge_type,
        evidence_excerpt=result.evidence_excerpt or "",
        # 9 扩展字段
        provider_metadata=provider_meta,
        cost_metadata=cost_meta,
        relevance_score=result.relevance_score,
        source_credibility_score=result.source_credibility_score,
        final_score=result.final_score,
        computation_trace=copy.deepcopy(result.computation_trace),
        suggested_action=suggested_action,
        candidate_for_ingest=True,
        ingest_status="pending",
        ingest_reason="外部搜索结果默认进入待审候选池",
        original_search_query=query,
        tags=list(sub_tags),
    )

    return card


def map_batch(
    results: list[SearchResult],
    task_type: str = "",
    query: str = "",
    estimated_cost: float = 0.0,
) -> list[IndustryIntelligenceCard]:
    """批量映射 SearchResult → IndustryIntelligenceCard。

    跳过必填字段缺失的结果（不抛异常，跳过并记录）。
    """
    cards: list[IndustryIntelligenceCard] = []
    for r in results:
        try:
            card = map_search_result_to_card(
                r, task_type=task_type, query=query,
                estimated_cost=estimated_cost,
            )
            cards.append(card)
        except MapperError:
            # 跳过必填字段缺失的结果
            continue
    return cards
