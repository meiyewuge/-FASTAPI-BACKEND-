"""测试 industry_mapper 推断逻辑。"""

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
from search_router.models.search_request import TaskType


class TestInferDimension:
    """推断一级维度。"""

    def test_keyword_ingredient(self):
        assert infer_industry_dimension("烟酰胺成分研究", "") == "原材料与成分"

    def test_keyword_packaging(self):
        assert infer_industry_dimension("包装设计", "") == "包装与包材"

    def test_keyword_ai(self):
        assert infer_industry_dimension("AI视频生成工具", "") == "数字化与AI工具"

    def test_fallback_task_type(self):
        assert infer_industry_dimension("", TaskType.GLOBAL_AI_TOOLS.value) == "数字化与AI工具"

    def test_fallback_default(self):
        assert infer_industry_dimension("", "") == "内容与营销打法"


class TestInferSubTags:
    """推断二级标签。"""

    def test_ingredient_tags(self):
        tags = infer_sub_tags("原材料与成分", "烟酰胺")
        assert "烟酰胺" in tags

    def test_empty_query(self):
        tags = infer_sub_tags("研发技术", "")
        assert isinstance(tags, list)


class TestInferRiskCategory:
    """推断风险分类。"""

    def test_ingredient_safety(self):
        assert infer_risk_category("成分安全检测", "ingredient") == "ingredient_safety"

    def test_medical_aesthetic(self):
        assert infer_risk_category("医美行业观察", "compliance") == "medical_aesthetic"

    def test_legal_policy(self):
        assert infer_risk_category("广告法合规", "compliance") == "legal_policy"

    def test_normal(self):
        assert infer_risk_category("美业营销趋势", "marketing") == "normal"


class TestBusinessRelevance:
    """业务相关度。"""

    def test_store_direct(self):
        r = infer_business_relevance("门店与服务项目", "store_case")
        assert "直接相关" in r

    def test_unknown(self):
        r = infer_business_relevance("未知维度", "trend")
        assert r == "待评估"


class TestApplicableScenario:
    """适用场景。"""

    def test_medical_aesthetic_safe(self):
        s = infer_applicable_scenario("medical_aesthetic", "trend")
        assert "观察" in s or "不得" in s

    def test_medical_aesthetic_unsafe(self):
        s = infer_applicable_scenario("medical_aesthetic", "store_case")
        assert "禁止" in s or "不得" in s

    def test_high_standard(self):
        s = infer_applicable_scenario("efficacy_claim", "ingredient")
        assert "高标准" in s

    def test_normal(self):
        s = infer_applicable_scenario("normal", "trend")
        assert "门店" in s


class TestRiskNotes:
    """风险备注。"""

    def test_medical_safe(self):
        n = build_risk_notes("medical_aesthetic", "trend")
        assert "医美" in n

    def test_high_standard(self):
        n = build_risk_notes("efficacy_claim", "ingredient")
        assert "高标准" in n

    def test_normal(self):
        n = build_risk_notes("normal", "trend")
        assert "无特殊风险" in n


class TestSuggestedAction:
    """建议动作。"""

    def test_high_standard(self):
        a = build_suggested_action("efficacy_claim", 0.9)
        assert "高标准" in a

    def test_medical_aesthetic(self):
        a = build_suggested_action("medical_aesthetic", 0.9)
        assert "不入库" in a or "观察" in a

    def test_high_confidence(self):
        a = build_suggested_action("normal", 0.8)
        assert "采纳" in a

    def test_medium_confidence(self):
        a = build_suggested_action("normal", 0.5)
        assert "核实" in a

    def test_low_confidence(self):
        a = build_suggested_action("normal", 0.2)
        assert "参考" in a


class TestLegalPolicyOfficialSource:
    """legal_policy 官方来源检查。"""

    def test_gov_cn_is_official(self):
        assert is_legal_policy_official_source("https://nmpa.gov.cn/notice/123") is True

    def test_non_gov_not_official(self):
        assert is_legal_policy_official_source("https://example.com/news") is False

    def test_empty_url(self):
        assert is_legal_policy_official_source("") is False
