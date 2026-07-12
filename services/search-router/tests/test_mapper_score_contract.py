"""Mapper Score Contract 专项测试 — 验证5个评分字段完整传播。

修复内容:
1. relevance_score 不再被 confidence*0.8 覆盖，直接传播 result.relevance_score
2. source_credibility_score 从 result 传播
3. final_score 从 result 传播
4. computation_trace 从 result 深拷贝传播
"""

import copy
import math
import pytest

from search_router.mapper import (
    map_search_result_to_card,
    map_batch,
    MapperError,
)
from search_router.models.search_response import SearchResult
from search_router.models.intelligence_card import IndustryIntelligenceCard


_DEFAULT_TRACE = {"weights": {"confidence": 0.45, "freshness": 0.25, "credibility": 0.30}, "steps": []}


def _make_search_result(
    title: str = "美业数字化转型趋势",
    url: str = "https://example.com/test",
    summary: str = "2026年美业数字化转型加速",
    provider: str = "bocha",
    confidence: float = 0.8,
    freshness: float = 0.7,
    relevance: float = 0.75,
    source_credibility: float = 0.6,
    final: float = 0.65,
    computation_trace: dict | None = None,
) -> SearchResult:
    trace = computation_trace if computation_trace is not None else _DEFAULT_TRACE
    return SearchResult(
        title=title,
        url=url,
        summary=summary,
        provider=provider,
        confidence_score=confidence,
        freshness_score=freshness,
        relevance_score=relevance,
        source_credibility_score=source_credibility,
        final_score=final,
        computation_trace=trace,
        evidence_excerpt="调查显示78%门店计划引入AI",
        source="美业观察网",
        publish_time="2026-06-20T08:30:00",
    )


class TestScoreFieldPropagation:
    """五个评分字段逐一验证从 SearchResult 传播到 IndustryIntelligenceCard。"""

    def test_confidence_score_propagated(self):
        """confidence_score 正确传播。"""
        r = _make_search_result(confidence=0.88)
        card = map_search_result_to_card(r)
        assert card.confidence_score == 0.88

    def test_freshness_score_propagated(self):
        """freshness_score 正确传播。"""
        r = _make_search_result(freshness=0.55)
        card = map_search_result_to_card(r)
        assert card.freshness_score == 0.55

    def test_relevance_score_propagated(self):
        """relevance_score 直接传播，不被 confidence*0.8 覆盖。"""
        r = _make_search_result(confidence=0.8, relevance=0.75)
        card = map_search_result_to_card(r)
        assert card.relevance_score == 0.75

    def test_source_credibility_score_propagated(self):
        """source_credibility_score 正确传播。"""
        r = _make_search_result(source_credibility=0.6)
        card = map_search_result_to_card(r)
        assert card.source_credibility_score == 0.6

    def test_final_score_propagated(self):
        """final_score 正确传播。"""
        r = _make_search_result(final=0.65)
        card = map_search_result_to_card(r)
        assert card.final_score == 0.65


class TestRelevanceScoreNotOverwritten:
    """relevance_score 不被 confidence*0.8 覆盖。"""

    def test_relevance_not_confidence_times_08(self):
        """relevance_score 不得等于 confidence*0.8（除非数值偶然相等）。"""
        # 构造 confidence*0.8 != relevance 的情况
        r = _make_search_result(confidence=0.9, relevance=0.75)
        card = map_search_result_to_card(r)
        # 0.9 * 0.8 = 0.72, relevance=0.75, 应该不相等
        assert card.relevance_score != 0.9 * 0.8

    def test_relevance_equals_result_relevance(self):
        """relevance_score 等于 result.relevance_score。"""
        r = _make_search_result(relevance=0.42)
        card = map_search_result_to_card(r)
        assert card.relevance_score == r.relevance_score


class TestFinalScoreNotNaN:
    """final_score 不再回落为 NaN。"""

    def test_final_score_not_nan_when_result_has_value(self):
        """result 有 final_score 时 card 不为 NaN。"""
        r = _make_search_result(final=0.7)
        card = map_search_result_to_card(r)
        assert not math.isnan(card.final_score)

    def test_final_score_nan_when_result_is_nan(self):
        """result 的 final_score 为 NaN 时允许传播 NaN（不覆盖默认值）。"""
        r = _make_search_result()
        r_final_nan = SearchResult(
            title=r.title, url=r.url, summary=r.summary,
            provider=r.provider, confidence_score=r.confidence_score,
            freshness_score=r.freshness_score,
            relevance_score=r.relevance_score,
            # final_score 默认 NaN
        )
        card = map_search_result_to_card(r_final_nan)
        assert math.isnan(card.final_score)


class TestZeroScorePreserved:
    """合法 0.0 保持 0.0。"""

    def test_zero_relevance_preserved(self):
        """relevance_score=0.0 保持 0.0。"""
        r = _make_search_result(relevance=0.0)
        card = map_search_result_to_card(r)
        assert card.relevance_score == 0.0

    def test_zero_source_credibility_preserved(self):
        """source_credibility_score=0.0 保持 0.0。"""
        r = _make_search_result(source_credibility=0.0)
        card = map_search_result_to_card(r)
        assert card.source_credibility_score == 0.0

    def test_zero_final_score_preserved(self):
        """final_score=0.0 保持 0.0。"""
        r = _make_search_result(final=0.0)
        card = map_search_result_to_card(r)
        assert card.final_score == 0.0


class TestDifferentScoresPropagated:
    """A/B/C/D 不同评分均原样传播。"""

    def test_distinct_scores_all_propagated(self):
        """四个不同评分值原样传播。"""
        r = _make_search_result(
            confidence=0.90,
            freshness=0.60,
            relevance=0.75,
            source_credibility=0.50,
            final=0.70,
        )
        card = map_search_result_to_card(r)
        assert card.confidence_score == 0.90
        assert card.freshness_score == 0.60
        assert card.relevance_score == 0.75
        assert card.source_credibility_score == 0.50
        assert card.final_score == 0.70


class TestComputationTracePropagation:
    """computation_trace 深拷贝传播。"""

    def test_computation_trace_propagated(self):
        """computation_trace 正确传播。"""
        trace = {"weights": {"confidence": 0.45, "freshness": 0.25, "credibility": 0.30}, "steps": ["step1", "step2"]}
        r = _make_search_result(computation_trace=trace)
        card = map_search_result_to_card(r)
        assert card.computation_trace == trace

    def test_computation_trace_is_deep_copy(self):
        """computation_trace 是深拷贝，修改 card 不影响 result。"""
        trace = {"weights": {"confidence": 0.45}, "steps": ["step1"]}
        r = _make_search_result(computation_trace=trace)
        card = map_search_result_to_card(r)
        # 修改 card 的 trace 不应影响 result
        card.computation_trace["weights"]["confidence"] = 999
        assert r.computation_trace["weights"]["confidence"] == 0.45

    def test_computation_trace_empty_dict(self):
        """空 dict 也能传播。"""
        r = _make_search_result(computation_trace={})
        card = map_search_result_to_card(r)
        assert card.computation_trace == {}


class TestProviderResultMapping:
    """Mock/Tavily/Bocha/GLM 结构结果映射正确。"""

    def test_mock_result_mapping(self):
        """Mock provider 结果映射正确。"""
        r = SearchResult(
            title="Mock测试", url="https://mock.com/1",
            provider="mock", confidence_score=0.5, freshness_score=0.4,
            relevance_score=0.3, source_credibility_score=0.2,
            final_score=0.35, computation_trace={"source": "mock"},
        )
        card = map_search_result_to_card(r, query="测试")
        assert card.relevance_score == 0.3
        assert card.source_credibility_score == 0.2
        assert card.final_score == 0.35
        assert card.computation_trace == {"source": "mock"}

    def test_tavily_result_mapping(self):
        """Tavily provider 结果映射正确。"""
        r = SearchResult(
            title="Tavily测试", url="https://tavily.com/1",
            provider="tavily", confidence_score=0.7, freshness_score=0.8,
            relevance_score=0.65, source_credibility_score=0.55,
            final_score=0.60, computation_trace={"source": "tavily"},
        )
        card = map_search_result_to_card(r, query="测试")
        assert card.relevance_score == 0.65
        assert card.source_credibility_score == 0.55
        assert card.final_score == 0.60

    def test_bocha_result_mapping(self):
        """Bocha provider 结果映射正确。"""
        r = SearchResult(
            title="Bocha测试", url="https://bocha.com/1",
            provider="bocha", confidence_score=0.85, freshness_score=0.75,
            relevance_score=0.80, source_credibility_score=0.70,
            final_score=0.78, computation_trace={"source": "bocha"},
        )
        card = map_search_result_to_card(r, query="测试")
        assert card.relevance_score == 0.80
        assert card.source_credibility_score == 0.70
        assert card.final_score == 0.78

    def test_glm_result_mapping(self):
        """GLM provider 结果映射正确。"""
        r = SearchResult(
            title="GLM测试", url="https://glm.com/1",
            provider="glm", confidence_score=0.6, freshness_score=0.5,
            relevance_score=0.55, source_credibility_score=0.45,
            final_score=0.50, computation_trace={"source": "glm"},
        )
        card = map_search_result_to_card(r, query="测试")
        assert card.relevance_score == 0.55
        assert card.source_credibility_score == 0.45
        assert card.final_score == 0.50


class TestNonScoreFieldsUnchanged:
    """title/URL/source/publish_time 不变。"""

    def test_non_score_fields_unchanged(self):
        """非评分字段映射不变。"""
        r = _make_search_result()
        card = map_search_result_to_card(r, query="美业AI")
        assert card.title == r.title
        assert card.url == r.url
        assert card.source == r.source
        assert card.publish_time == r.publish_time


class TestBatchNoCrossContamination:
    """map_batch 多条结果不串值。"""

    def test_batch_no_cross_contamination(self):
        """批量映射时各结果评分不串值。"""
        results = [
            SearchResult(
                title=f"结果{i}", url=f"https://example.com/{i}",
                provider="mock", confidence_score=0.1 * (i + 1),
                freshness_score=0.2 * (i + 1), relevance_score=0.3 * (i + 1),
                source_credibility_score=0.4 * (i + 1), final_score=0.5 * (i + 1),
                computation_trace={"idx": i},
            )
            for i in range(4)
        ]
        cards = map_batch(results, query="测试")
        assert len(cards) == 4
        for i, card in enumerate(cards):
            assert card.confidence_score == pytest.approx(0.1 * (i + 1))
            assert card.relevance_score == pytest.approx(0.3 * (i + 1))
            assert card.source_credibility_score == pytest.approx(0.4 * (i + 1))
            assert card.final_score == pytest.approx(0.5 * (i + 1))
            assert card.computation_trace == {"idx": i}


class TestInputNotMutated:
    """输入对象不被 Mapper 修改。"""

    def test_result_not_mutated(self):
        """map_search_result_to_card 不修改输入 SearchResult。"""
        trace = {"weights": {"confidence": 0.45}, "steps": ["step1"]}
        r = _make_search_result(
            confidence=0.8, relevance=0.75,
            source_credibility=0.6, final=0.65,
            computation_trace=trace,
        )
        # 保存原始值
        orig_relevance = r.relevance_score
        orig_credibility = r.source_credibility_score
        orig_final = r.final_score
        orig_trace = r.computation_trace
        card = map_search_result_to_card(r)
        # 验证输入不变
        assert r.relevance_score == orig_relevance
        assert r.source_credibility_score == orig_credibility
        assert r.final_score == orig_final
        assert r.computation_trace is orig_trace  # 同一对象
        # 验证输出正确
        assert card.relevance_score == orig_relevance
        assert card.source_credibility_score == orig_credibility
        assert card.final_score == orig_final
