"""测试风险分类（7 risk_category）+ 高标准审核规则。"""

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


class TestRiskCategories:
    """7 risk_category。"""

    def test_7_risk_categories(self):
        assert len(RISK_CATEGORIES) == 7

    def test_expected_categories(self):
        expected = {
            "normal", "commercial_claim", "efficacy_claim",
            "ingredient_safety", "medical_aesthetic",
            "legal_policy", "privacy_data",
        }
        assert set(RISK_CATEGORIES) == expected

    def test_snake_case(self):
        """所有 risk_category 值使用 snake_case。"""
        for rc in RISK_CATEGORIES:
            assert "_" in rc or rc == "normal", f"非 snake_case: {rc}"
            assert rc == rc.lower(), f"非小写: {rc}"

    def test_no_camelcase(self):
        """禁止 camelCase。"""
        forbidden = [
            "storeCase", "aiTool", "medicalAesthetic",
            "legalPolicy", "ingredientSafety", "efficacyClaim",
            "commercialClaim", "privacyData",
        ]
        for f in forbidden:
            assert f not in RISK_CATEGORIES


class TestHighStandardsReview:
    """高标准审核。"""

    def test_efficacy_claim_needs_review(self):
        assert needs_high_standard_review("efficacy_claim") is True

    def test_ingredient_safety_needs_review(self):
        assert needs_high_standard_review("ingredient_safety") is True

    def test_legal_policy_needs_review(self):
        assert needs_high_standard_review("legal_policy") is True

    def test_normal_no_review(self):
        assert needs_high_standard_review("normal") is False

    def test_commercial_claim_no_review(self):
        assert needs_high_standard_review("commercial_claim") is False

    def test_medical_aesthetic_no_high_standard(self):
        """医美不在高标准审核集合（有独立规则）。"""
        assert needs_high_standard_review("medical_aesthetic") is False


class TestMedicalAesthetic:
    """医美规则。"""

    def test_is_medical_aesthetic(self):
        assert is_medical_aesthetic("medical_aesthetic") is True

    def test_is_not_medical_aesthetic(self):
        assert is_medical_aesthetic("normal") is False

    def test_medical_safe_trend(self):
        assert is_medical_aesthetic_safe("trend") is True

    def test_medical_safe_compliance(self):
        assert is_medical_aesthetic_safe("compliance") is True

    def test_medical_safe_policy(self):
        assert is_medical_aesthetic_safe("policy") is True

    def test_medical_unsafe_store_case(self):
        """医美内容 store_case 不安全（不得自动转门店建议）。"""
        assert is_medical_aesthetic_safe("store_case") is False

    def test_medical_unsafe_marketing(self):
        assert is_medical_aesthetic_safe("marketing") is False

    def test_medical_allowed_types_count(self):
        """医美安全知识类型 3 种。"""
        assert len(MEDICAL_AESTHETIC_ALLOWED_KNOWLEDGE_TYPES) == 3
