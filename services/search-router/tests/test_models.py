"""测试 SearchRequest / SearchResponse / SearchResult 数据类。"""

import pytest
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import (
    SearchResponse,
    SearchResult,
    ProviderType,
    ErrorCode,
)


class TestTaskType:
    """TaskType 枚举（蛇形命名）。"""

    def test_snake_case_values(self):
        """TaskType 值使用蛇形命名。"""
        assert TaskType.CHINESE_INDUSTRY_NEWS.value == "chinese_industry_news"
        assert TaskType.GLOBAL_AI_TOOLS.value == "global_ai_tools"
        assert TaskType.OFFICIAL_DOCS.value == "official_docs"
        assert TaskType.TECHNICAL_RESEARCH.value == "technical_research"
        assert TaskType.FALLBACK_LIGHT_SEARCH.value == "fallback_light_search"

    def test_task_type_count(self):
        """5 种任务类型。"""
        assert len(TaskType) == 5


class TestProviderType:
    """ProviderType 枚举（蛇形命名）。"""

    def test_snake_case_values(self):
        """ProviderType 值使用蛇形命名。"""
        assert ProviderType.MOCK.value == "mock"
        assert ProviderType.PRIMARY.value == "primary"
        assert ProviderType.FALLBACK.value == "fallback"
        assert ProviderType.EMERGENCY.value == "emergency"

    def test_provider_type_count(self):
        """4 种 Provider 类型。"""
        assert len(ProviderType) == 4


class TestSearchRequest:
    """SearchRequest 数据类。"""

    def test_basic_construction(self):
        """基本构造。"""
        req = SearchRequest(query="美业AI", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        assert req.query == "美业AI"
        assert req.task_type == TaskType.CHINESE_INDUSTRY_NEWS
        assert req.max_results == 10
        assert req.language_hint == "zh"

    def test_max_results_capped_at_20(self):
        """max_results 上限 20。"""
        req = SearchRequest(query="test", max_results=100)
        assert req.max_results == 20

    def test_max_results_minimum_1(self):
        """max_results 下限 1。"""
        req = SearchRequest(query="test", max_results=0)
        assert req.max_results == 1

    def test_empty_query_raises(self):
        """空 query 抛 ValueError。"""
        with pytest.raises(ValueError, match="query 不能为空"):
            SearchRequest(query="")

    def test_whitespace_query_raises(self):
        """纯空白 query 抛 ValueError。"""
        with pytest.raises(ValueError, match="query 不能为空"):
            SearchRequest(query="   ")

    def test_to_dict(self):
        """to_dict() 输出正确。"""
        req = SearchRequest(
            query="AI视频生成",
            task_type=TaskType.GLOBAL_AI_TOOLS,
            max_results=5,
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
            need_ai_summary=True,
        )
        d = req.to_dict()
        assert d["query"] == "AI视频生成"
        assert d["task_type"] == "global_ai_tools"
        assert d["max_results"] == 5
        assert "example.com" in d["include_domains"]
        assert "spam.com" in d["exclude_domains"]
        assert d["need_ai_summary"] is True

    def test_default_domains_empty(self):
        """include/exclude_domains 默认空列表。"""
        req = SearchRequest(query="test")
        assert req.include_domains == []
        assert req.exclude_domains == []


class TestSearchResult:
    """SearchResult 数据类。"""

    def test_basic_construction(self):
        """基本构造。"""
        r = SearchResult(title="测试", url="https://example.com/test")
        assert r.title == "测试"
        assert r.url == "https://example.com/test"
        assert r.summary == ""

    def test_to_dict(self):
        """to_dict() 输出正确。"""
        r = SearchResult(
            title="AI美业趋势",
            url="https://example.com/ai-trend",
            summary="AI技术在美业的应用趋势",
            source="美业观察",
            provider="mock",
            confidence_score=0.85,
        )
        d = r.to_dict()
        assert d["title"] == "AI美业趋势"
        assert d["url"] == "https://example.com/ai-trend"
        assert d["confidence_score"] == 0.85
        assert d["provider"] == "mock"


class TestSearchResponse:
    """SearchResponse 数据类。"""

    def test_default_values(self):
        """默认值。"""
        resp = SearchResponse()
        assert resp.success is True
        assert resp.provider == "mock"
        assert resp.provider_type == ProviderType.MOCK
        assert resp.results == []
        assert resp.total_results == 0
        assert resp.estimated_cost == 0.0
        assert resp.error is None
        assert resp.error_code == "none"

    def test_total_results_auto_from_results(self):
        """total_results 自动从 results 长度同步。"""
        results = [
            SearchResult(title="r1", url="https://example.com/1"),
            SearchResult(title="r2", url="https://example.com/2"),
        ]
        resp = SearchResponse(results=results)
        assert resp.total_results == 2

    def test_to_dict(self):
        """to_dict() 输出正确。"""
        results = [SearchResult(title="test", url="https://example.com")]
        resp = SearchResponse(
            success=True,
            provider="mock",
            provider_type=ProviderType.MOCK,
            results=results,
            total_results=1,
            latency_ms=50,
            credits_used=0,
            estimated_cost=0.0,
        )
        d = resp.to_dict()
        assert d["success"] is True
        assert d["provider"] == "mock"
        assert d["provider_type"] == "mock"
        assert d["total_results"] == 1
        assert d["latency_ms"] == 50
        assert d["estimated_cost"] == 0.0
        assert len(d["results"]) == 1

    def test_error_response(self):
        """错误响应。"""
        resp = SearchResponse(
            success=False,
            provider="bocha",
            provider_type=ProviderType.PRIMARY,
            error="API Key 无效",
            error_code="auth_fail",
        )
        assert resp.success is False
        assert resp.error == "API Key 无效"
        assert resp.error_code == "auth_fail"


class TestErrorCode:
    """ErrorCode 枚举。"""

    def test_error_code_values(self):
        """ErrorCode 值。"""
        assert ErrorCode.NONE.value == "none"
        assert ErrorCode.AUTH_FAIL.value == "auth_fail"
        assert ErrorCode.COST_EXCEEDED.value == "cost_exceeded"
