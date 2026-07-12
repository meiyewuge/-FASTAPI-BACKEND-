"""测试 TavilyAdapter（T2A）。

所有 HTTP 请求由内联的 mock session 拦截：
    - 不接真实 Key（统一使用 api_key="test_key_xxx"）
    - 不联网、不调真实 Tavily API
    - 不依赖 aioresponses / aiohttp（纯标准库 mock）
"""

import asyncio
import inspect

import pytest

from search_router.adapters import tavily as tavily_module
from search_router.adapters.tavily import TavilyAdapter
from search_router.adapters.base import BaseProviderAdapter
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import SearchResponse, ProviderType, ErrorCode
from search_router.scorers.confidence_scorer import compute_relevance_from_tavily_score


TEST_KEY = "test_key_xxx"


# ── 内联 mock session（绝不联网）────────────────────────

class _FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    """按 URL 路由返回，可同时支持 search + extract 两个端点。"""

    def __init__(self, routes=None, status=200, payload=None):
        self.routes = routes or {}
        self._status = status
        self._payload = payload if payload is not None else {}
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append({"url": url, "json": json, "headers": headers, "kwargs": kwargs})
        status, payload = self.routes.get(url, (self._status, self._payload))
        return _FakeResp(status, payload)

    async def close(self):
        self.closed = True


def _search_response():
    return {
        "query": "AI video tools",
        "answer": "Top AI video tools in 2026.",
        "results": [
            {
                "title": "Runway Gen-3",
                "url": "https://runway.example/gen3",
                "content": "Runway Gen-3 delivers high fidelity AI video.",
                "score": 0.93,
                "published_date": "2026-06-10",
            },
            {
                "title": "Pika 1.5",
                "url": "https://pika.example/1-5",
                "content": "Pika 1.5 adds lip sync and motion brush.",
                "score": 0.88,
                "published_date": "2026-06-08",
            },
        ],
    }


def _extract_response():
    return {
        "results": [
            {"url": "https://runway.example/gen3", "raw_content": "FULL RUNWAY ARTICLE BODY"},
        ],
        "failed_results": [],
    }


def _req(**kw):
    kw.setdefault("query", "AI video tools")
    kw.setdefault("task_type", TaskType.GLOBAL_AI_TOOLS)
    return SearchRequest(**kw)


# ── 基本契约 ───────────────────────────────────────────

def test_is_base_adapter():
    assert isinstance(TavilyAdapter(api_key=TEST_KEY), BaseProviderAdapter)


def test_provider_name():
    assert TavilyAdapter(api_key=TEST_KEY).provider_name == "tavily"


def test_provider_type_primary():
    assert TavilyAdapter(api_key=TEST_KEY).provider_type == ProviderType.PRIMARY


def test_is_available_with_key():
    assert TavilyAdapter(api_key=TEST_KEY).is_available() is True


def test_is_available_empty_key():
    assert TavilyAdapter(api_key="").is_available() is False


def test_validate_config():
    assert TavilyAdapter(api_key=TEST_KEY).validate_config() is True
    assert TavilyAdapter(api_key="").validate_config() is False


# ── 成本：basic / advanced / extract ───────────────────

def test_estimate_cost_basic():
    assert TavilyAdapter(api_key=TEST_KEY).estimate_cost(_req(need_ai_summary=False)) == 0.056


def test_estimate_cost_advanced():
    assert TavilyAdapter(api_key=TEST_KEY).estimate_cost(_req(need_ai_summary=True)) == 0.112


def test_estimate_cost_basic_plus_extract_empty_domains():
    # need_extract 不依赖 include_domains：空 domains 仍按 min(max_results, 5) 计
    cost = TavilyAdapter(api_key=TEST_KEY).estimate_cost(
        _req(need_extract=True, max_results=5, include_domains=[])
    )
    assert cost == 0.336  # 0.056 + 5×0.056


def test_estimate_cost_extract_counts_by_max_results_capped_at_5():
    # max_results=10 时 Extract 仍按 5 个 URL 计（min(10, 5)）
    cost = TavilyAdapter(api_key=TEST_KEY).estimate_cost(
        _req(need_extract=True, max_results=10)
    )
    assert cost == 0.336  # 0.056 + 5×0.056


def test_estimate_cost_advanced_plus_extract():
    cost = TavilyAdapter(api_key=TEST_KEY).estimate_cost(
        _req(need_ai_summary=True, need_extract=True, max_results=5)
    )
    assert cost == 0.392  # 0.112 + 5×0.056


# ── 请求构造 ───────────────────────────────────────────

def test_build_headers_bearer():
    headers = TavilyAdapter(api_key=TEST_KEY)._build_headers()
    assert headers["Authorization"] == f"Bearer {TEST_KEY}"
    assert headers["Content-Type"] == "application/json"


def test_build_payload_basic_branch():
    payload = TavilyAdapter(api_key=TEST_KEY)._build_payload(_req(need_ai_summary=False))
    assert payload["search_depth"] == "basic"
    assert payload["include_answer"] is False


def test_build_payload_advanced_branch():
    payload = TavilyAdapter(api_key=TEST_KEY)._build_payload(_req(need_ai_summary=True))
    assert payload["search_depth"] == "advanced"
    assert payload["include_answer"] is True


def test_build_payload_domains_passthrough():
    payload = TavilyAdapter(api_key=TEST_KEY)._build_payload(
        _req(include_domains=["openai.com"], exclude_domains=["spam.com"])
    )
    assert payload["include_domains"] == ["openai.com"]
    assert payload["exclude_domains"] == ["spam.com"]


def test_build_payload_max_results_capped_at_10():
    payload = TavilyAdapter(api_key=TEST_KEY)._build_payload(_req(max_results=20))
    assert payload["max_results"] == 10


# ── search 端到端 + 标准化 ─────────────────────────────

def test_search_basic_uses_search_endpoint():
    session = _FakeSession(payload=_search_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(need_ai_summary=False)))
    assert resp.success is True
    assert session.calls[0]["url"] == TavilyAdapter.SEARCH_ENDPOINT
    assert session.calls[0]["json"]["search_depth"] == "basic"
    assert resp.estimated_cost == 0.056


def test_search_advanced_branch():
    session = _FakeSession(payload=_search_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(need_ai_summary=True)))
    assert resp.success is True
    assert session.calls[0]["json"]["search_depth"] == "advanced"
    assert resp.estimated_cost == 0.112


def test_search_normalizes_result_fields():
    session = _FakeSession(payload=_search_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.total_results == 2
    first = resp.results[0]
    assert first.title == "Runway Gen-3"
    assert first.url == "https://runway.example/gen3"
    assert "high fidelity" in first.summary          # content → summary
    assert first.publish_time == "2026-06-10"         # published_date → publish_time
    # Phase1: relevance经tanh规范化, 不直接等于raw score
    raw_score = 0.93
    expected_relevance, _ = compute_relevance_from_tavily_score(raw_score)
    assert first.relevance_score == pytest.approx(expected_relevance)
    assert first.relevance_score != raw_score         # 不等于原始score
    assert first.relevance_score != first.confidence_score  # 不等于confidence
    assert first.provider == "tavily"
    assert first.raw["score"] == 0.93                 # 原始字段进 raw


def test_search_empty_key_returns_auth_fail_without_call():
    session = _FakeSession(payload=_search_response())
    adapter = TavilyAdapter(api_key="", session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.AUTH_FAIL.value
    assert session.calls == []


def test_search_non_200_maps_rate_limit():
    session = _FakeSession(status=429, payload={})
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.RATE_LIMIT.value


# ── Extract 分支 ───────────────────────────────────────

def test_search_with_extract_calls_extract_endpoint():
    routes = {
        TavilyAdapter.SEARCH_ENDPOINT: (200, _search_response()),
        TavilyAdapter.EXTRACT_ENDPOINT: (200, _extract_response()),
    }
    session = _FakeSession(routes=routes)
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(need_extract=True)))
    called = [c["url"] for c in session.calls]
    assert TavilyAdapter.SEARCH_ENDPOINT in called
    assert TavilyAdapter.EXTRACT_ENDPOINT in called
    # 抽取的正文合并回对应结果的 raw
    runway = next(r for r in resp.results if r.url == "https://runway.example/gen3")
    assert runway.raw["extracted_content"] == "FULL RUNWAY ARTICLE BODY"


def test_extract_urls_capped_at_5():
    many = {"results": [
        {"title": f"t{i}", "url": f"https://e.example/{i}", "content": "c", "score": 0.5}
        for i in range(8)
    ]}
    routes = {
        TavilyAdapter.SEARCH_ENDPOINT: (200, many),
        TavilyAdapter.EXTRACT_ENDPOINT: (200, _extract_response()),
    }
    session = _FakeSession(routes=routes)
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    asyncio.run(adapter.search(_req(need_extract=True, max_results=10)))
    extract_call = next(c for c in session.calls if c["url"] == TavilyAdapter.EXTRACT_ENDPOINT)
    assert len(extract_call["json"]["urls"]) == 5  # 最多 5 个 URL


def test_no_extract_when_flag_false():
    session = _FakeSession(payload=_search_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    asyncio.run(adapter.search(_req(need_extract=False)))
    assert all(c["url"] != TavilyAdapter.EXTRACT_ENDPOINT for c in session.calls)


def test_result_count_capped_at_10():
    many = {"results": [
        {"title": f"t{i}", "url": f"https://e.example/{i}", "content": "c", "score": 0.5}
        for i in range(25)
    ]}
    session = _FakeSession(payload=many)
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(max_results=10)))
    assert len(resp.results) <= 10


# ── 网络安全：注入 session 路径绝不触达 aiohttp ─────────

def test_no_real_network_via_injected_session(monkeypatch):
    def _boom():
        raise AssertionError("真实网络路径被触发：不应导入 aiohttp！")

    monkeypatch.setattr(tavily_module, "_require_aiohttp", _boom)
    session = _FakeSession(payload=_search_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
