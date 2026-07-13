"""测试 BochaAdapter（T2A）。

所有 HTTP 请求由内联的 mock session 拦截：
    - 不接真实 Key（统一使用 api_key="test_key_xxx"）
    - 不联网、不调真实 Bocha API
    - 不依赖 aioresponses / aiohttp（纯标准库 mock）
"""

import asyncio
import inspect

import pytest

from search_router.adapters import bocha as bocha_module
from search_router.adapters.bocha import BochaAdapter
from search_router.adapters.base import BaseProviderAdapter
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import SearchResponse, ProviderType, ErrorCode


TEST_KEY = "test_key_xxx"


# ── 内联 mock session（绝不联网）────────────────────────

class _FakeResp:
    """模拟 aiohttp 响应的 async context manager。"""

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
    """模拟 aiohttp.ClientSession：记录调用、按 URL 路由返回，绝不联网。"""

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


def _web_response():
    return {
        "code": 200,
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "美业AI趋势报告 2026",
                        "url": "https://example.cn/ai-trend",
                        "snippet": "2026 美业 AI 应用快速增长。",
                        "summary": "完整摘要：2026 年美业 AI 渗透率显著提升，门店智能化成主流。",
                        "siteName": "美业观察网",
                        "datePublished": "2026-06-20T08:30:00",
                        "dateLastCrawled": "2026-06-21T00:00:00",
                    },
                    {
                        "name": "门店数字化白皮书",
                        "url": "https://example.cn/whitepaper",
                        "snippet": "门店数字化转型方法论。",
                        "summary": "门店数字化白皮书完整内容。",
                        "siteName": "数字美业",
                        "datePublished": "2026-06-18T10:00:00",
                    },
                ]
            }
        },
    }


def _ai_response():
    resp = _web_response()
    resp["data"]["answer"] = "AI 总结：2026 美业 AI 趋势向好。"
    return resp


def _req(**kw):
    kw.setdefault("query", "美业AI趋势")
    kw.setdefault("task_type", TaskType.CHINESE_INDUSTRY_NEWS)
    return SearchRequest(**kw)


# ── 基本契约 ───────────────────────────────────────────

def test_is_base_adapter():
    assert isinstance(BochaAdapter(api_key=TEST_KEY), BaseProviderAdapter)


def test_provider_name():
    assert BochaAdapter(api_key=TEST_KEY).provider_name == "bocha"


def test_provider_type_primary():
    assert BochaAdapter(api_key=TEST_KEY).provider_type == ProviderType.PRIMARY


def test_is_available_with_key():
    assert BochaAdapter(api_key=TEST_KEY).is_available() is True


def test_is_available_empty_key():
    assert BochaAdapter(api_key="").is_available() is False
    assert BochaAdapter(api_key="   ").is_available() is False


def test_validate_config():
    assert BochaAdapter(api_key=TEST_KEY).validate_config() is True
    assert BochaAdapter(api_key="").validate_config() is False


# ── 成本 ───────────────────────────────────────────────

def test_estimate_cost_web():
    assert BochaAdapter(api_key=TEST_KEY).estimate_cost(_req(need_ai_summary=False)) == 0.036


def test_estimate_cost_ai():
    assert BochaAdapter(api_key=TEST_KEY).estimate_cost(_req(need_ai_summary=True)) == 0.060


# ── 请求构造 ───────────────────────────────────────────

def test_build_headers_bearer():
    headers = BochaAdapter(api_key=TEST_KEY)._build_headers()
    assert headers["Authorization"] == f"Bearer {TEST_KEY}"
    assert headers["Content-Type"] == "application/json"


def test_build_payload_web_branch():
    payload = BochaAdapter(api_key=TEST_KEY)._build_payload(_req(need_ai_summary=False, max_results=5))
    assert payload["query"] == "美业AI趋势"
    assert payload["count"] == 5
    assert payload["summary"] is True
    assert "answer" not in payload


def test_build_payload_ai_branch():
    payload = BochaAdapter(api_key=TEST_KEY)._build_payload(_req(need_ai_summary=True))
    assert payload["answer"] is True
    assert payload["stream"] is False
    assert "summary" not in payload


def test_build_payload_count_capped_at_20():
    # SearchRequest 自身上限 20；payload count 不超过 20
    payload = BochaAdapter(api_key=TEST_KEY)._build_payload(_req(max_results=20))
    assert payload["count"] == 20


def test_freshness_mapping():
    a = BochaAdapter(api_key=TEST_KEY)
    assert a._map_freshness("day") == "oneDay"
    assert a._map_freshness("oneWeek") == "oneWeek"
    assert a._map_freshness("month") == "oneMonth"
    assert a._map_freshness(None) == "noLimit"
    assert a._map_freshness("unknown") == "noLimit"


# ── search 分支：Web vs AI 端点 ─────────────────────────

def test_search_web_uses_web_endpoint():
    session = _FakeSession(payload=_web_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(need_ai_summary=False)))
    assert resp.success is True
    assert session.calls[0]["url"] == BochaAdapter.WEB_SEARCH_ENDPOINT
    assert resp.estimated_cost == 0.036


def test_search_ai_uses_ai_endpoint():
    session = _FakeSession(payload=_ai_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(need_ai_summary=True)))
    assert resp.success is True
    assert session.calls[0]["url"] == BochaAdapter.AI_SEARCH_ENDPOINT
    assert resp.estimated_cost == 0.060


# ── 标准化 + 响应字段 ──────────────────────────────────

def test_search_returns_search_response():
    session = _FakeSession(payload=_web_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert isinstance(resp, SearchResponse)
    assert resp.provider == "bocha"
    assert resp.provider_type == ProviderType.PRIMARY
    assert resp.error_code == ErrorCode.NONE.value


def test_search_normalizes_result_fields():
    session = _FakeSession(payload=_web_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.total_results == 2
    first = resp.results[0]
    assert first.title == "美业AI趋势报告 2026"
    assert first.url == "https://example.cn/ai-trend"
    assert "渗透率" in first.summary           # 取 summary 长文
    assert first.source == "美业观察网"          # siteName → source
    assert first.publish_time == "2026-06-20T08:30:00"
    assert first.provider == "bocha"
    assert first.evidence_excerpt == "2026 美业 AI 应用快速增长。"  # snippet
    assert first.raw["dateLastCrawled"] == "2026-06-21T00:00:00"   # 原始字段进 raw


def test_search_request_headers_carry_bearer():
    session = _FakeSession(payload=_web_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    asyncio.run(adapter.search(_req()))
    assert session.calls[0]["headers"]["Authorization"] == f"Bearer {TEST_KEY}"


def test_search_empty_key_returns_auth_fail_without_call():
    session = _FakeSession(payload=_web_response())
    adapter = BochaAdapter(api_key="", session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.AUTH_FAIL.value
    assert session.calls == []  # 不发任何请求


def test_search_non_200_maps_error_code():
    session = _FakeSession(status=401, payload={})
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.AUTH_FAIL.value


def test_result_count_capped_at_20():
    big = {"data": {"webPages": {"value": [
        {"name": f"r{i}", "url": f"https://e.cn/{i}", "snippet": "s"} for i in range(50)
    ]}}}
    session = _FakeSession(payload=big)
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req(max_results=20)))
    assert len(resp.results) <= 20


# ── 网络安全：注入 session 路径绝不触达 aiohttp ─────────

def test_no_real_network_via_injected_session(monkeypatch):
    """patch _require_aiohttp 为抛异常：search 仍成功 ⇒ 证明不走真实网络。"""
    def _boom():
        raise AssertionError("真实网络路径被触发：不应导入 aiohttp！")

    monkeypatch.setattr(bocha_module, "_require_aiohttp", _boom)
    session = _FakeSession(payload=_web_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True  # 未触发 _require_aiohttp


def test_module_has_no_toplevel_network_import():
    """模块顶层不得直接 import 网络库（aiohttp 仅惰性导入于函数内）。"""
    src = inspect.getsource(bocha_module)
    # 顶层不出现裸 import；aiohttp 仅以惰性形式存在于 _require_aiohttp 内
    assert "\nimport aiohttp" not in src
    assert "\nimport requests" not in src
    assert "\nimport httpx" not in src
