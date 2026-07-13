"""industry 包入口 — 产业字段资产（从 V0.1.3 Mock 迁移复用）。

迁移自: /opt/wuge-labs/search-router-mock-v0.1.3/wuge_search_router/search_router/
口径: 12 维度 / 77 标签 / 12 knowledge_type / 7 risk_category — 完全一致
"""

from search_router.industry.industry_taxonomy import (
    INDUSTRY_DIMENSIONS,
    INDUSTRY_SUB_TAGS,
    all_sub_tags_count,
    get_dimension,
    validate_sub_tag,
    validate_sub_tags,
)
from search_router.industry.risk_classifier import (
    KnowledgeType,
    RiskCategory,
    KNOWLEDGE_TYPES,
    RISK_CATEGORIES,
    HIGH_STANDARDS_REVIEW,
    MEDICAL_AESTHETIC_ALLOWED_KNOWLEDGE_TYPES,
    needs_high_standard_review,
    is_medical_aesthetic_safe,
    is_medical_aesthetic,
)
from search_router.industry.knowledge_type_mapper import (
    map_task_to_knowledge_type,
    infer_knowledge_type,
)
from search_router.industry.industry_mapper import (
    infer_industry_dimension,
    infer_sub_tags,
    infer_risk_category,
    infer_business_relevance,
    infer_applicable_scenario,
    build_risk_notes,
    build_suggested_action,
)

__all__ = [
    # taxonomy
    "INDUSTRY_DIMENSIONS",
    "INDUSTRY_SUB_TAGS",
    "all_sub_tags_count",
    "get_dimension",
    "validate_sub_tag",
    "validate_sub_tags",
    # risk_classifier
    "KnowledgeType",
    "RiskCategory",
    "KNOWLEDGE_TYPES",
    "RISK_CATEGORIES",
    "HIGH_STANDARDS_REVIEW",
    "MEDICAL_AESTHETIC_ALLOWED_KNOWLEDGE_TYPES",
    "needs_high_standard_review",
    "is_medical_aesthetic_safe",
    "is_medical_aesthetic",
    # knowledge_type_mapper
    "map_task_to_knowledge_type",
    "infer_knowledge_type",
    # industry_mapper
    "infer_industry_dimension",
    "infer_sub_tags",
    "infer_risk_category",
    "infer_business_relevance",
    "infer_applicable_scenario",
    "build_risk_notes",
    "build_suggested_action",
]
