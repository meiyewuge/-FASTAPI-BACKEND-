"""产业映射器：推断产业分类、标签、知识类型和风险分类。

迁移自 V0.1.3 Mock，核心推断逻辑完全一致。
import 路径适配 T2B 基线。
不依赖 V0.1.3 的 ProviderResult / CostUsage / RouteDecision（T2B 无此类型）。
"""

from __future__ import annotations

from search_router.industry.industry_taxonomy import (
    INDUSTRY_DIMENSIONS,
    INDUSTRY_SUB_TAGS,
    validate_sub_tags,
)
from search_router.industry.knowledge_type_mapper import infer_knowledge_type
from search_router.industry.risk_classifier import (
    RiskCategory,
    is_medical_aesthetic,
    is_medical_aesthetic_safe,
    needs_high_standard_review,
)
from search_router.models.search_request import TaskType


# 任务类型 → 默认一级维度
_TASK_TO_DIMENSION = {
    TaskType.CHINESE_INDUSTRY_NEWS.value: "门店与服务项目",
    TaskType.GLOBAL_AI_TOOLS.value: "数字化与AI工具",
    TaskType.OFFICIAL_DOCS.value: "政策法规与合规",
    TaskType.TECHNICAL_RESEARCH.value: "研发技术",
    TaskType.FALLBACK_LIGHT_SEARCH.value: "内容与营销打法",
}


# 关键词 → 一级维度
_KEYWORD_TO_DIMENSION = [
    (["成分", "烟酰胺", "玻尿酸", "视黄醇", "肽", "提取物", "防腐剂", "防晒剂"], "原材料与成分"),
    (["包装", "瓶", "泵头", "安瓶", "包材", "真空"], "包装与包材"),
    (["gmpc", "iso", "代工", "oem", "odm", "无尘车间", "产线"], "生产制造"),
    (["品牌", "定位", "高端线", "大众线", "产品线"], "品牌与产品"),
    (["面部护理", "spa", "抗衰项目", "祛痘", "纹绣", "美甲", "美睫", "生发", "头皮"], "门店与服务项目"),
    (["电商", "专柜", "免税", "直播带货", "经销商", "跨境", "冷链"], "渠道与供应链"),
    (["成分党", "颜值经济", "他经济", "银发", "z世代", "国潮", "纯净美妆"], "消费者与用户趋势"),
    (["短视频", "直播", "kol", "种草", "私域", "裂变", "品牌ip"], "内容与营销打法"),
    (["ai视频", "ai客服", "肤质检测", "智能推荐", "saas", "crm", "数字化门店"], "数字化与AI工具"),
    (["nmpa", "备案", "功效评价", "广告法", "标签合规", "医美监管", "数据隐私"], "政策法规与合规"),
    (["融资", "并购", "ipo", "估值", "产业园区", "出口", "行业报告", "市场规模"], "投融资并购与产业动态"),
    (["研发", "配方", "功效成分", "皮肤科学", "生物技术", "干细胞", "基因", "临床试验"], "研发技术"),
]


def infer_industry_dimension(query: str, task_type: str = "") -> str:
    """根据 query 关键词推断一级维度。"""
    q = (query or "").lower()
    for keywords, dim in _KEYWORD_TO_DIMENSION:
        if any(kw in q for kw in keywords):
            return dim
    return _TASK_TO_DIMENSION.get(task_type, "内容与营销打法")


def infer_sub_tags(dimension: str, query: str = "") -> list[str]:
    """根据一级维度和 query 推断二级标签。"""
    all_tags = INDUSTRY_SUB_TAGS.get(dimension, [])
    if not query:
        return all_tags[:2]  # 默认返回前 2 个
    q = query.lower()
    matched = [t for t in all_tags if t.lower() in q or q in t.lower()]
    return matched if matched else all_tags[:2]


def infer_risk_category(query: str, knowledge_type: str = "") -> str:
    """根据内容推断风险分类。"""
    q = (query or "").lower()

    # 医美
    if any(kw in q for kw in ["医美", "注射", "激光", "热玛吉", "超声刀", "埋线", "肉毒素"]):
        return RiskCategory.MEDICAL_AESTHETIC.value
    # 功效宣称
    if any(kw in q for kw in ["功效", "美白", "抗皱", "祛斑", "生发", "减肥", "疗效"]):
        return RiskCategory.EFFICACY_CLAIM.value
    # 成分安全
    if any(kw in q for kw in ["防腐剂", "重金属", "激素", "过敏", "毒性", "刺激性", "成分安全", "成分检测"]):
        return RiskCategory.INGREDIENT_SAFETY.value
    # 法律政策
    if any(kw in q for kw in ["nmpa", "法规", "监管", "处罚", "违规", "广告法", "合规"]):
        return RiskCategory.LEGAL_POLICY.value
    # 隐私数据
    if any(kw in q for kw in ["隐私", "数据泄露", "个人信息", "gdpr", "数据安全"]):
        return RiskCategory.PRIVACY_DATA.value
    # 商业宣称
    if any(kw in q for kw in ["销量第一", "最佳", "全网最低", "神器", "根治"]):
        return RiskCategory.COMMERCIAL_CLAIM.value

    return RiskCategory.NORMAL.value


def infer_business_relevance(dimension: str, knowledge_type: str = "") -> str:
    """推断业务相关度描述。"""
    relevance_map = {
        "门店与服务项目": "直接相关：门店服务项目优化与升级",
        "内容与营销打法": "直接相关：门店内容生产与营销获客",
        "数字化与AI工具": "直接相关：门店数字化升级与AI工具应用",
        "品牌与产品": "相关：品牌定位与产品选择",
        "研发技术": "间接相关：技术趋势影响服务方案",
        "原材料与成分": "间接相关：成分知识支持顾客咨询",
        "政策法规与合规": "重要：合规要求直接影响门店经营",
        "投融资并购与产业动态": "参考：行业趋势影响战略决策",
    }
    return relevance_map.get(dimension, "待评估")


def infer_applicable_scenario(risk_category: str, knowledge_type: str = "") -> str:
    """推断适用场景。"""
    if is_medical_aesthetic(risk_category):
        if is_medical_aesthetic_safe(knowledge_type):
            return "仅做趋势/合规/行业观察参考，不得自动转为生活美容门店建议"
        return "医美内容，仅限行业观察，禁止转为门店操作建议"
    if needs_high_standard_review(risk_category):
        return "需高标准审核后才能用于业务决策"
    return "可用于门店经营参考"


def build_risk_notes(risk_category: str, knowledge_type: str) -> str:
    """构建风险备注。"""
    if is_medical_aesthetic(risk_category):
        if is_medical_aesthetic_safe(knowledge_type):
            return "医美内容：仅做趋势/合规/行业观察，不得自动转为生活美容门店建议"
        return "医美内容：知识类型不在安全范围内，需人工审核"
    if needs_high_standard_review(risk_category):
        return f"风险分类 {risk_category}：需高标准审核后才能入库"
    return "无特殊风险"


def build_suggested_action(risk_category: str, confidence_score: float) -> str:
    """构建建议动作。"""
    if needs_high_standard_review(risk_category):
        return "高标准审核：需人工核实后入库"
    if is_medical_aesthetic(risk_category):
        return "仅限行业观察参考，不入库为门店操作建议"
    if confidence_score >= 0.7:
        return "建议采纳，待审核入库"
    if confidence_score >= 0.4:
        return "建议人工核实后入库"
    return "建议仅作参考，不入库"


def is_legal_policy_official_source(url: str) -> bool:
    """legal_policy 类优先要求官方来源（.gov.cn）。"""
    if not url:
        return False
    url_lower = url.lower()
    return ".gov.cn" in url_lower or "nmpa.gov.cn" in url_lower
