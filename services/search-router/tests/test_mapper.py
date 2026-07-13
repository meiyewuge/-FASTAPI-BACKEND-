"""测试 SearchResultMapper — SearchResult → IndustryIntelligenceCard 映射。"""

import pytest
from search_router.mapper import (
    map_search_result_to_card,
    map_batch,
    MapperError,
    REQUIRED_FIELDS,
)
from search_router.models.search_response import SearchResult
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.models.search_request import TaskType


def _make_search_result(
    title: str = "美业数字化转型趋势",
    url: str = "https://example.com/test",
    summary: str = "2026年美业数字化转型加速",
    provider: str = "bocha",
    confidence: float = 0.8,
) -> SearchResult:
    return SearchResult(
        title=title,
        url=url,
        summary=summary,
        provider=provider,
        confidence_score=confidence,
        freshness_score=0.7,
        evidence_excerpt="调查显示78%门店计划引入AI",
        source="美业观察网",
        publish_time="2026-06-20T08:30:00",
    )


class TestMapperBasic:
    """基础映射。"""

    def test_map_basic(self):
        """SearchResult → IndustryIntelligenceCard 基础映射。"""
        r = _make_search_result()
        card = map_search_result_to_card(r, task_type="chinese_industry_news", query="美业AI")
        assert isinstance(card, IndustryIntelligenceCard)
        assert card.title == r.title
        assert card.url == r.url
        assert card.summary == r.summary
        assert card.source == r.source
        assert card.publish_time == r.publish_time

    def test_17_core_fields_present(self):
        """17 核心字段全部存在。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        core_names = IndustryIntelligenceCard.core_field_names()
        assert len(core_names) == 17
        for name in core_names:
            assert hasattr(card, name), f"缺少核心字段: {name}"

    def test_9_extension_fields_present(self):
        """9 扩展字段全部存在。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        ext_names = IndustryIntelligenceCard.extension_field_names()
        assert len(ext_names) == 9
        for name in ext_names:
            assert hasattr(card, name), f"缺少扩展字段: {name}"

    def test_fetched_at_auto_generated(self):
        """fetched_at 自动生成。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert card.fetched_at
        assert "T" in card.fetched_at  # ISO format

    def test_provider_metadata_has_provider(self):
        """provider_metadata 记录 provider。"""
        r = _make_search_result(provider="bocha")
        card = map_search_result_to_card(r)
        assert card.provider_metadata["provider"] == "bocha"

    def test_provider_metadata_has_raw(self):
        """provider_metadata 记录 raw 信息。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert "raw" in card.provider_metadata
        assert card.provider_metadata["raw"]["title"] == r.title

    def test_cost_metadata(self):
        """cost_metadata 预留。"""
        r = _make_search_result()
        card = map_search_result_to_card(r, estimated_cost=0.036)
        assert card.cost_metadata["estimated_cost"] == 0.036

    def test_confidence_freshness_inherited(self):
        """confidence_score / freshness_score 继承 SearchResult。"""
        r = _make_search_result(confidence=0.85)
        card = map_search_result_to_card(r)
        assert card.confidence_score == 0.85

    def test_merged_from_passed_through(self):
        """merged_from 正确传递。"""
        r = _make_search_result()
        card = map_search_result_to_card(r, merged_from=["mock", "tavily"])
        assert card.provider_metadata["merged_from"] == ["mock", "tavily"]


class TestMapperDefaults:
    """默认值验证。"""

    def test_candidate_for_ingest_default_true(self):
        """candidate_for_ingest 默认 True。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert card.candidate_for_ingest is True

    def test_ingest_status_default_pending(self):
        """ingest_status 默认 pending。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert card.ingest_status == "pending"

    def test_ingest_reason_default(self):
        """ingest_reason 默认值。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert "待审候选池" in card.ingest_reason

    def test_no_formal_status(self):
        """禁止 formal 状态。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert card.ingest_status != "formal"

    def test_country_default_china(self):
        """country_or_region 默认中国。"""
        r = _make_search_result()
        card = map_search_result_to_card(r)
        assert card.country_or_region == "中国"


class TestMapperRequiredFields:
    """必填字段缺失拒绝映射。"""

    def test_empty_title_raises(self):
        """title 为空 → MapperError。"""
        r = _make_search_result(title="")
        with pytest.raises(MapperError):
            map_search_result_to_card(r)

    def test_empty_url_raises(self):
        """url 为空 → MapperError。"""
        r = _make_search_result(url="")
        with pytest.raises(MapperError):
            map_search_result_to_card(r)

    def test_whitespace_title_raises(self):
        """title 全空白 → MapperError。"""
        r = _make_search_result(title="   ")
        with pytest.raises(MapperError):
            map_search_result_to_card(r)


class TestMapperBatch:
    """批量映射。"""

    def test_batch_maps_all(self):
        """批量映射全部成功。"""
        results = [
            _make_search_result(url=f"https://example.com/{i}")
            for i in range(5)
        ]
        cards = map_batch(results, task_type="chinese_industry_news", query="美业AI")
        assert len(cards) == 5

    def test_batch_skips_invalid(self):
        """跳过必填字段缺失的结果。"""
        results = [
            _make_search_result(url="https://example.com/valid"),
            _make_search_result(title="", url="https://example.com/invalid"),
        ]
        cards = map_batch(results)
        assert len(cards) == 1


class TestMapperIndustryFields:
    """产业字段推断。"""

    def test_industry_dimension_inferred(self):
        """industry_dimension 被推断。"""
        r = _make_search_result(title="美业AI视频生成工具")
        card = map_search_result_to_card(r, task_type="global_ai_tools")
        assert card.industry_dimension  # 非空

    def test_knowledge_type_inferred(self):
        """knowledge_type 被推断。"""
        r = _make_search_result(title="AI视频生成工具")
        card = map_search_result_to_card(r, task_type="global_ai_tools")
        assert card.knowledge_type  # 非空

    def test_risk_category_inferred(self):
        """risk_category 被推断。"""
        r = _make_search_result(title="烟酰胺成分安全检测")
        card = map_search_result_to_card(r)
        assert card.risk_category  # 非空

    def test_risk_notes_for_medical_aesthetic(self):
        """医美内容 risk_notes 包含限制说明。"""
        r = _make_search_result(title="医美行业趋势观察")
        card = map_search_result_to_card(r)
        assert "医美" in card.risk_notes or "观察" in card.risk_notes

    def test_suggested_action_not_store_advice_for_medical(self):
        """医美内容 suggested_action 不自动转门店建议。"""
        r = _make_search_result(title="医美行业趋势观察")
        card = map_search_result_to_card(r)
        assert "门店操作建议" not in card.suggested_action or "不入库" in card.suggested_action

    def test_legal_policy_non_official_source_warned(self):
        """legal_policy 非官方来源时 risk_notes 有提示。"""
        r = _make_search_result(
            title="广告法合规新规定",
            url="https://example.com/news",  # 非 .gov.cn
        )
        card = map_search_result_to_card(r)
        assert "官方来源" in card.risk_notes or "gov.cn" in card.risk_notes

    def test_legal_policy_official_source_ok(self):
        """legal_policy 官方来源（.gov.cn）不报警。"""
        r = _make_search_result(
            title="广告法合规新规定",
            url="https://nmpa.gov.cn/notice/123",
        )
        card = map_search_result_to_card(r)
        assert "非官方" not in card.risk_notes
