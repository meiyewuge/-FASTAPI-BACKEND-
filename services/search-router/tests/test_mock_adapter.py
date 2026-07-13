"""测试 MockProviderAdapter。"""

import asyncio
import pytest
from search_router.adapters.mock import MockProviderAdapter
from search_router.adapters.base import BaseProviderAdapter
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import SearchResponse, ProviderType


class TestMockProviderAdapter:
    """MockProviderAdapter 测试。"""

    def test_is_base_adapter(self):
        """MockProviderAdapter 是 BaseProviderAdapter 子类。"""
        adapter = MockProviderAdapter()
        assert isinstance(adapter, BaseProviderAdapter)

    def test_provider_name(self):
        """provider_name 默认 mock。"""
        adapter = MockProviderAdapter()
        assert adapter.provider_name == "mock"

    def test_provider_name_custom(self):
        """自定义 provider_name。"""
        adapter = MockProviderAdapter(provider_name="bocha_mock")
        assert adapter.provider_name == "bocha_mock"

    def test_provider_type_is_mock(self):
        """provider_type 始终为 MOCK。"""
        adapter = MockProviderAdapter()
        assert adapter.provider_type == ProviderType.MOCK

    def test_is_available_always_true(self):
        """Mock 始终可用。"""
        adapter = MockProviderAdapter()
        assert adapter.is_available() is True

    def test_estimate_cost_zero(self):
        """Mock 成本为 0。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="test", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        assert adapter.estimate_cost(req) == 0.0

    def test_validate_config_always_true(self):
        """Mock 配置始终合法。"""
        adapter = MockProviderAdapter()
        assert adapter.validate_config() is True

    def test_search_returns_response(self):
        """search 返回 SearchResponse。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="美业AI", task_type=TaskType.CHINESE_INDUSTRY_NEWS, max_results=3)
        resp = asyncio.run(adapter.search(req))
        assert isinstance(resp, SearchResponse)
        assert resp.success is True
        assert resp.provider == "mock"
        assert resp.provider_type == ProviderType.MOCK

    def test_search_returns_results(self):
        """search 返回搜索结果列表。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS, max_results=5)
        resp = asyncio.run(adapter.search(req))
        assert len(resp.results) > 0
        assert all(r.title for r in resp.results)
        assert all(r.url for r in resp.results)

    def test_search_credits_zero(self):
        """Mock 不消耗 credits。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="test", task_type=TaskType.GLOBAL_AI_TOOLS)
        resp = asyncio.run(adapter.search(req))
        assert resp.credits_used == 0

    def test_search_cost_zero(self):
        """Mock 不产生成本。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="test", task_type=TaskType.GLOBAL_AI_TOOLS)
        resp = asyncio.run(adapter.search(req))
        assert resp.estimated_cost == 0.0

    def test_search_respects_max_results(self):
        """max_results 限制返回数量。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="test", task_type=TaskType.CHINESE_INDUSTRY_NEWS, max_results=2)
        resp = asyncio.run(adapter.search(req))
        assert len(resp.results) <= 2

    def test_search_different_task_types(self):
        """不同 task_type 返回不同 mock 数据。"""
        adapter = MockProviderAdapter()

        req_cn = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp_cn = asyncio.run(adapter.search(req_cn))
        assert any("美业" in r.title or "美业" in r.summary for r in resp_cn.results)

        req_en = SearchRequest(query="AI video", task_type=TaskType.GLOBAL_AI_TOOLS)
        resp_en = asyncio.run(adapter.search(req_en))
        assert any("AI" in r.title or "video" in r.title.lower() for r in resp_en.results)

    def test_search_total_results_sync(self):
        """total_results 与 results 长度一致。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="test", task_type=TaskType.OFFICIAL_DOCS)
        resp = asyncio.run(adapter.search(req))
        assert resp.total_results == len(resp.results)

    def test_search_no_network_calls(self):
        """Mock 不联网（验证不 import requests/httpx/aiohttp）。"""
        # 验证 mock 模块不依赖任何网络库
        import search_router.adapters.mock as mock_module
        import inspect
        source = inspect.getsource(mock_module)
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "import aiohttp" not in source
        assert "import urllib" not in source

    def test_search_results_have_provider_tag(self):
        """搜索结果 provider 字段标记为 mock。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="test", task_type=TaskType.TECHNICAL_RESEARCH)
        resp = asyncio.run(adapter.search(req))
        assert all(r.provider == "mock" for r in resp.results)
