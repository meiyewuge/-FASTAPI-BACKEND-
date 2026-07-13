"""综合验证 12 维度 + 77 标签 + 12 knowledge_type + 7 risk_category + 17 核心字段。"""

from search_router.industry.industry_taxonomy import (
    INDUSTRY_DIMENSIONS,
    INDUSTRY_SUB_TAGS,
    all_sub_tags_count,
)
from search_router.industry.risk_classifier import (
    KNOWLEDGE_TYPES,
    RISK_CATEGORIES,
    HIGH_STANDARDS_REVIEW,
)
from search_router.models.intelligence_card import (
    IndustryIntelligenceCard,
    ALLOWED_INGEST_STATUSES,
    FORBIDDEN_INGEST_STATUS,
)
from search_router.mapper import map_search_result_to_card
from search_router.models.search_response import SearchResult


class TestFullIndustryFields:
    """全量产业字段验证。"""

    def test_12_dimensions(self):
        assert len(INDUSTRY_DIMENSIONS) == 12

    def test_77_sub_tags(self):
        assert all_sub_tags_count() == 77

    def test_12_knowledge_types(self):
        assert len(KNOWLEDGE_TYPES) == 12

    def test_7_risk_categories(self):
        assert len(RISK_CATEGORIES) == 7

    def test_17_core_fields(self):
        assert len(IndustryIntelligenceCard.core_field_names()) == 17

    def test_9_extension_fields(self):
        assert len(IndustryIntelligenceCard.extension_field_names()) == 9

    def test_all_snake_case(self):
        """所有枚举值 snake_case。"""
        for kt in KNOWLEDGE_TYPES:
            assert kt == kt.lower()
        for rc in RISK_CATEGORIES:
            assert rc == rc.lower()

    def test_no_camelcase_anywhere(self):
        forbidden = [
            "storeCase", "aiTool", "medicalAesthetic", "legalPolicy",
            "ingredientSafety", "efficacyClaim", "commercialClaim",
            "privacyData", "supplyChain",
        ]
        all_enums = set(KNOWLEDGE_TYPES) | set(RISK_CATEGORIES)
        for f in forbidden:
            assert f not in all_enums


class TestIntelligenceCardValidation:
    """IntelligenceCard 验证规则。"""

    def test_formal_forbidden(self):
        assert FORBIDDEN_INGEST_STATUS == "formal"

    def test_formal_not_in_allowed(self):
        assert "formal" not in ALLOWED_INGEST_STATUSES

    def test_pending_in_allowed(self):
        assert "pending" in ALLOWED_INGEST_STATUSES

    def test_default_ingest_status_pending(self):
        card = IndustryIntelligenceCard()
        assert card.ingest_status == "pending"

    def test_default_candidate_true(self):
        card = IndustryIntelligenceCard()
        assert card.candidate_for_ingest is True

    def test_set_formal_raises(self):
        card = IndustryIntelligenceCard()
        with __import__("pytest").raises(ValueError):
            card.ingest_status = "formal"
            card.__post_init__()


class TestEndToEndMapping:
    """端到端映射验证。"""

    def test_full_mapping_preserves_all_fields(self):
        """完整映射不丢失字段。"""
        r = SearchResult(
            title="美业AI视频生成工具趋势",
            url="https://example.com/ai-video",
            summary="AI视频生成工具在美业门店的应用趋势",
            source="美业观察网",
            publish_time="2026-06-20T08:30:00",
            provider="bocha",
            evidence_excerpt="78%门店计划引入AI",
            confidence_score=0.85,
            freshness_score=0.7,
        )
        card = map_search_result_to_card(r, task_type="global_ai_tools", query="AI视频")
        
        # 核心字段
        assert card.title == r.title
        assert card.url == r.url
        assert card.summary == r.summary
        assert card.source == r.source
        assert card.publish_time == r.publish_time
        assert card.evidence_excerpt == r.evidence_excerpt
        assert card.confidence_score == 0.85
        assert card.freshness_score == 0.7
        assert card.fetched_at  # 自动生成
        assert card.country_or_region == "中国"
        assert card.industry_dimension  # 推断
        assert card.knowledge_type  # 推断
        assert card.risk_category  # 推断
        assert card.risk_notes  # 推断
        assert card.business_relevance  # 推断
        assert card.applicable_scenario  # 推断

        # 扩展字段
        assert card.provider_metadata["provider"] == "bocha"
        assert card.candidate_for_ingest is True
        assert card.ingest_status == "pending"
        assert card.ingest_reason
        assert card.original_search_query == "AI视频"
