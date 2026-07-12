"""知识类型映射器：任务类型 / 搜索内容 → knowledge_type。

迁移自 V0.1.3 Mock，口径完全一致。
import 路径适配 T2B 基线（search_router.models.search_request）。
"""

from __future__ import annotations

from search_router.industry.risk_classifier import KnowledgeType
from search_router.models.search_request import TaskType


# 任务类型 → 默认 knowledge_type
_TASK_TO_KNOWLEDGE = {
    TaskType.CHINESE_INDUSTRY_NEWS.value: KnowledgeType.STORE_CASE.value,
    TaskType.GLOBAL_AI_TOOLS.value: KnowledgeType.AI_TOOL.value,
    TaskType.OFFICIAL_DOCS.value: KnowledgeType.COMPLIANCE.value,
    TaskType.TECHNICAL_RESEARCH.value: KnowledgeType.TECH.value,
    TaskType.FALLBACK_LIGHT_SEARCH.value: KnowledgeType.TREND.value,
}


def map_task_to_knowledge_type(task_type: str) -> str:
    """任务类型 → knowledge_type。"""
    return _TASK_TO_KNOWLEDGE.get(task_type, KnowledgeType.TREND.value)


def infer_knowledge_type(query: str, task_type: str = "") -> str:
    """根据 query 关键词推断 knowledge_type。"""
    q = (query or "").lower()

    # 成分
    if any(kw in q for kw in ["成分", "烟酰胺", "玻尿酸", "视黄醇", "肽", "提取物", "防腐剂"]):
        return KnowledgeType.INGREDIENT.value
    # 包装
    if any(kw in q for kw in ["包装", "瓶", "泵头", "安瓶", "包材"]):
        return KnowledgeType.PACKAGING.value
    # 品牌
    if any(kw in q for kw in ["品牌", "新锐", "高端线", "大众线"]):
        return KnowledgeType.BRAND.value
    # 产品
    if any(kw in q for kw in ["产品", "产品线", "功效型", "敏感肌"]):
        return KnowledgeType.PRODUCT.value
    # 营销
    if any(kw in q for kw in ["营销", "种草", "直播", "短视频", "裂变", "私域"]):
        return KnowledgeType.MARKETING.value
    # 供应链
    if any(kw in q for kw in ["供应链", "物流", "经销商", "跨境", "冷链"]):
        return KnowledgeType.SUPPLY_CHAIN.value
    # AI工具
    if any(kw in q for kw in ["ai", "人工智能", "视频生成", "saas", "crm", "数字化"]):
        return KnowledgeType.AI_TOOL.value
    # 技术
    if any(kw in q for kw in ["技术", "研发", "配方", "临床", "干细胞", "基因"]):
        return KnowledgeType.TECH.value
    # 趋势
    if any(kw in q for kw in ["趋势", "报告", "市场", "规模", "投融资", "并购"]):
        return KnowledgeType.TREND.value

    # 回落到任务类型映射
    return map_task_to_knowledge_type(task_type)
