"""风险分类枚举（7 种）与知识类型枚举（12 种）+ 高标准审核规则。

基于《美丽大健康全球产业链数据采集与入库标准 V0.1.1》。
迁移自 V0.1.3 Mock，口径完全一致。

枚举值全部使用 snake_case（蛇形命名）。
"""

from __future__ import annotations

from enum import Enum


class KnowledgeType(str, Enum):
    """12 种知识类型（snake_case）。"""
    TREND = "trend"                     # 趋势
    TECH = "tech"                       # 技术
    INGREDIENT = "ingredient"           # 成分
    PACKAGING = "packaging"             # 包装
    BRAND = "brand"                     # 品牌
    PRODUCT = "product"                 # 产品
    STORE_CASE = "store_case"           # 门店案例
    MARKETING = "marketing"             # 营销
    COMPLIANCE = "compliance"           # 合规
    AI_TOOL = "ai_tool"                 # AI工具
    SUPPLY_CHAIN = "supply_chain"       # 供应链
    POLICY = "policy"                   # 政策


KNOWLEDGE_TYPES = [kt.value for kt in KnowledgeType]


class RiskCategory(str, Enum):
    """7 种风险分类（snake_case）。"""
    NORMAL = "normal"                           # 无风险
    COMMERCIAL_CLAIM = "commercial_claim"       # 商业宣称
    EFFICACY_CLAIM = "efficacy_claim"           # 功效宣称
    INGREDIENT_SAFETY = "ingredient_safety"     # 成分安全
    MEDICAL_AESTHETIC = "medical_aesthetic"     # 医美
    LEGAL_POLICY = "legal_policy"               # 法规政策
    PRIVACY_DATA = "privacy_data"               # 隐私数据


RISK_CATEGORIES = [rc.value for rc in RiskCategory]

# 需要高标准审核的风险分类
HIGH_STANDARDS_REVIEW = {
    RiskCategory.EFFICACY_CLAIM.value,
    RiskCategory.INGREDIENT_SAFETY.value,
    RiskCategory.LEGAL_POLICY.value,
}

# 医美：只做趋势/合规/行业观察，不得自动转为生活美容门店建议
MEDICAL_AESTHETIC_ALLOWED_KNOWLEDGE_TYPES = {
    KnowledgeType.TREND.value,
    KnowledgeType.COMPLIANCE.value,
    KnowledgeType.POLICY.value,
}


def needs_high_standard_review(risk_category: str) -> bool:
    """是否需要高标准审核。"""
    return risk_category in HIGH_STANDARDS_REVIEW


def is_medical_aesthetic_safe(knowledge_type: str) -> bool:
    """医美内容的知识类型是否安全（只做趋势/合规/行业观察）。"""
    return knowledge_type in MEDICAL_AESTHETIC_ALLOWED_KNOWLEDGE_TYPES


def is_medical_aesthetic(risk_category: str) -> bool:
    """是否为医美风险分类。"""
    return risk_category == RiskCategory.MEDICAL_AESTHETIC.value
