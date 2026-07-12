"""测试 GLMSearchAdapter（T2A）。

所有 HTTP 请求由内联的 mock session 拦截：
    - 不接真实 Key（统一使用 api_key="test_key_xxx"）
    - 不联网、不调真实 GLM API
    - 不依赖 aioresponses / aiohttp（纯标准库 mock）
    - _chat_completion() 接口存在但不联网（预留 T4）
"""

import asyncio
import inspect

import pytest

from search_router.adapters import glm_search as glm_module
from search_router.adapters.glm_search import GLMSearchAdapter
from search_router.adapters.base import BaseProviderAdapter
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import SearchResponse, ProviderType, ErrorCode


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


def _glm_response():
    """旧 Chat Completions + web_search 响应格式（仅用于 _chat_completion 测试）。"""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "综合搜索结果如下。"}}
        ],
        "web_search": [
            {
                "title": "智谱 GLM 美业应用案例",
                "link": "https://zhipu.example.cn/case",
                "content": "GLM 在美业门店智能问答中的落地实践与效果数据。",
                "media": "智谱开放平台",
                "publish_date": "2026-06-19",
                "refer": "ref_1",
            },
            {
                "title": "门店 AI 助手对比评测",
                "link": "https://zhipu.example.cn/review",
                "content": "主流门店 AI 助手能力横评。",
                "media": "AI 评测",
                "publish_date": "2026-06-17",
                "refer": "ref_2",
            },
        ],
    }


def _web_search_response():
    """Web Search API 响应格式（search_result 数组）。"""
    return {
        "search_result": [
            {
                "title": "智谱 GLM 美业应用案例",
                "link": "https://zhipu.example.cn/case",
                "content": "GLM 在美业门店智能问答中的落地实践与效果数据。",
                "media": "智谱开放平台",
                "publish_date": "2026-06-19",
                "refer": "ref_1",
            },
            {
                "title": "门店 AI 助手对比评测",
                "link": "https://zhipu.example.cn/review",
                "content": "主流门店 AI 助手能力横评。",
                "media": "AI 评测",
                "publish_date": "2026-06-17",
                "refer": "ref_2",
            },
        ],
    }


def _req(**kw):
    kw.setdefault("query", "美业AI趋势")
    kw.setdefault("task_type", TaskType.CHINESE_INDUSTRY_NEWS)
    return SearchRequest(**kw)


# ── 基本契约 ───────────────────────────────────────────

def test_is_base_adapter():
    assert isinstance(GLMSearchAdapter(api_key=TEST_KEY), BaseProviderAdapter)


def test_provider_name():
    assert GLMSearchAdapter(api_key=TEST_KEY).provider_name == "glm_search"


def test_provider_type_fallback():
    # GLM 在 P0 中为通用 F2 备搜 / 免费 fallback 源
    assert GLMSearchAdapter(api_key=TEST_KEY).provider_type == ProviderType.FALLBACK


def test_is_available_with_key():
    assert GLMSearchAdapter(api_key=TEST_KEY).is_available() is True


def test_is_available_empty_key():
    assert GLMSearchAdapter(api_key="").is_available() is False


def test_validate_config():
    assert GLMSearchAdapter(api_key=TEST_KEY).validate_config() is True
    assert GLMSearchAdapter(api_key="").validate_config() is False


# ── 成本：免费 ─────────────────────────────────────────

def test_estimate_cost_free():
    a = GLMSearchAdapter(api_key=TEST_KEY)
    assert a.estimate_cost(_req(need_ai_summary=False)) == 0.0
    assert a.estimate_cost(_req(need_ai_summary=True)) == 0.0


# ── 请求构造 ───────────────────────────────────────────

def test_build_headers_bearer():
    headers = GLMSearchAdapter(api_key=TEST_KEY)._build_headers()
    assert headers["Authorization"] == f"Bearer {TEST_KEY}"
    assert headers["Content-Type"] == "application/json"


def test_build_payload_web_search_tool():
    payload = GLMSearchAdapter(api_key=TEST_KEY)._build_payload(_req())
    assert payload["model"] == "glm-4-flash"
    assert payload["messages"][0]["content"] == "美业AI趋势"
    tool = payload["tools"][0]
    assert tool["type"] == "web_search"
    assert tool["web_search"]["search_engine"] == "search_pro"
    assert tool["web_search"]["enable"] is True
    assert tool["web_search"]["search_result"] is True


def test_recency_mapping_default_oneweek():
    a = GLMSearchAdapter(api_key=TEST_KEY)
    assert a._map_recency(None) == "oneWeek"


def test_recency_mapping_explicit():
    a = GLMSearchAdapter(api_key=TEST_KEY)
    assert a._map_recency("day") == "oneDay"
    assert a._map_recency("week") == "oneWeek"
    assert a._map_recency("month") == "oneMonth"
    assert a._map_recency("year") == "oneYear"
    assert a._map_recency("oneYear") == "oneYear"
    assert a._map_recency("garbage") == "oneWeek"


def test_payload_recency_applied():
    payload = GLMSearchAdapter(api_key=TEST_KEY)._build_payload(_req(time_range="day"))
    assert payload["tools"][0]["web_search"]["search_recency_filter"] == "oneDay"


# ── search 端到端 ──────────────────────────────────────

def test_search_uses_web_search_endpoint():
    """search() 使用 /web_search endpoint，不是 /chat/completions。"""
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    assert session.calls[0]["url"] == GLMSearchAdapter.WEB_SEARCH_ENDPOINT


def test_search_returns_search_response_cost_zero():
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert isinstance(resp, SearchResponse)
    assert resp.provider == "glm_search"
    assert resp.provider_type == ProviderType.FALLBACK
    assert resp.estimated_cost == 0.0


def test_search_response_provider_type_fallback():
    # search 返回的 SearchResponse.provider_type 也必须是 fallback
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.provider_type == ProviderType.FALLBACK
    assert resp.provider_type.value == "fallback"


def test_search_normalizes_result_fields():
    """search() 从 search_result 数组标准化为 SearchResult。"""
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.total_results == 2
    first = resp.results[0]
    assert first.title == "智谱 GLM 美业应用案例"
    assert first.url == "https://zhipu.example.cn/case"   # link → url
    assert "落地实践" in first.summary                      # content → summary
    assert first.source == "智谱开放平台"                    # media → source
    assert first.publish_time == "2026-06-19"               # publish_date → publish_time
    assert first.provider == "glm_search"
    assert first.raw["refer"] == "ref_1"                    # 原始字段进 raw


def test_search_empty_key_returns_auth_fail_without_call():
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key="", session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.AUTH_FAIL.value
    assert session.calls == []


def test_search_non_200_maps_server_error():
    session = _FakeSession(status=500, payload={})
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.SERVER_ERROR.value


def test_extract_items_supports_tool_call_shape():
    """兼容 choices[].message.tool_calls[].search_result 承载。"""
    raw = {
        "choices": [
            {"message": {"tool_calls": [
                {"search_result": [
                    {"title": "t", "link": "https://e.cn/x", "content": "c", "media": "m"}
                ]}
            ]}}
        ]
    }
    items = GLMSearchAdapter(api_key=TEST_KEY)._extract_items(raw)
    assert len(items) == 1 and items[0]["title"] == "t"


# ── _chat_completion 预留接口：存在但不联网 ────────────

def test_chat_completion_is_coroutine_method():
    adapter = GLMSearchAdapter(api_key=TEST_KEY)
    assert hasattr(adapter, "_chat_completion")
    assert inspect.iscoroutinefunction(adapter._chat_completion)


def test_chat_completion_bridge_with_mocked_post():
    """_chat_completion 不再抛 NotImplementedError；mock _post 后返回正常响应。"""
    adapter = GLMSearchAdapter(api_key=TEST_KEY)

    # Mock _post to return a valid Chat Completions response
    mock_response = {
        "choices": [
            {"message": {"content": '{"risk_category":"normal","knowledge_type":"ai_tool"}'}}
        ]
    }

    async def mock_post(url, payload, headers):
        return 200, mock_response

    adapter._post = mock_post

    result = asyncio.run(adapter._chat_completion(
        [{"role": "user", "content": "test"}]
    ))
    assert result == mock_response
    assert result["choices"][0]["message"]["content"]


def test_chat_completion_no_api_key_raises():
    """_chat_completion 在 api_key 为空时抛 RuntimeError，不联网。"""
    adapter = GLMSearchAdapter(api_key="")
    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(adapter._chat_completion([{"role": "user", "content": "hi"}]))


def test_chat_completion_payload_no_web_search():
    """_chat_completion 的 payload 不含 tools / web_search。"""
    adapter = GLMSearchAdapter(api_key=TEST_KEY)

    captured_payload = {}

    async def mock_post(url, payload, headers):
        captured_payload.update(payload)
        return 200, {"choices": [{"message": {"content": "{}"}}]}

    adapter._post = mock_post
    asyncio.run(adapter._chat_completion([{"role": "user", "content": "hi"}]))

    assert captured_payload["model"] == "glm-4-flash"
    assert "tools" not in captured_payload
    assert "web_search" not in captured_payload
    assert "temperature" in captured_payload


def test_chat_completion_abnormal_response_raises():
    """响应缺少 choices 时抛 ValueError，供 Enhancer 降级。"""
    adapter = GLMSearchAdapter(api_key=TEST_KEY)

    async def mock_post(url, payload, headers):
        return 200, {"error": "something wrong"}  # 无 choices

    adapter._post = mock_post

    with pytest.raises(ValueError, match="choices"):
        asyncio.run(adapter._chat_completion([{"role": "user", "content": "hi"}]))


def test_chat_completion_http_error_raises():
    """非 200 响应抛 RuntimeError，供 Enhancer 降级。"""
    adapter = GLMSearchAdapter(api_key=TEST_KEY)

    async def mock_post(url, payload, headers):
        return 401, {"error": {"code": "401", "message": "令牌已过期"}}

    adapter._post = mock_post

    with pytest.raises(RuntimeError, match="HTTP 401"):
        asyncio.run(adapter._chat_completion([{"role": "user", "content": "hi"}]))


def test_build_chat_payload_has_no_web_search():
    """预留的 chat 体不含 web_search tool，不会触发联网检索。"""
    payload = GLMSearchAdapter(api_key=TEST_KEY)._build_chat_payload(
        [{"role": "user", "content": "hi"}]
    )
    assert payload["model"] == "glm-4-flash"
    assert payload["temperature"] == 0.1
    assert "tools" not in payload


# ── 网络安全：注入 session 路径绝不触达 aiohttp ─────────

def test_no_real_network_via_injected_session(monkeypatch):
    def _boom():
        raise AssertionError("真实网络路径被触发：不应导入 aiohttp！")

    monkeypatch.setattr(glm_module, "_require_aiohttp", _boom)
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True


# ── Phase 2 Web Search API Patch 专项测试 ──────────────


def test_web_search_payload_format():
    """search() payload 包含 search_query/count/search_engine，不含 messages/tools。"""
    session = _FakeSession(payload=_web_search_response())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    asyncio.run(adapter.search(_req()))
    payload = session.calls[0]["json"]
    assert "search_query" in payload
    assert "count" in payload
    assert "search_engine" in payload
    assert "messages" not in payload
    assert "tools" not in payload
    assert "web_search" not in payload


def test_web_search_link_media_empty_preserved():
    """link/media 为空时保留结果，不丢弃，raw 标记 _url_missing。"""
    response = {
        "search_result": [
            {
                "title": "无链接结果",
                "content": "内容但无 URL",
                "link": "",
                "media": "",
                "publish_date": "2026-06-27",
                "refer": "ref_empty",
            }
        ]
    }
    session = _FakeSession(payload=response)
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    assert resp.total_results == 1
    assert resp.results[0].url.startswith("glm-search://"), f"Expected fallback URL, got: {resp.results[0].url}"
    assert resp.results[0].raw.get("_url_missing") is True
    assert resp.results[0].raw["refer"] == "ref_empty"


def test_web_search_empty_result_success():
    """search_result 为空数组时 success=True, total_results=0。"""
    session = _FakeSession(payload={"search_result": []})
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    assert resp.total_results == 0
    assert resp.results == []


def test_web_search_no_search_result_key():
    """响应无 search_result key 时 success=True, total_results=0。"""
    session = _FakeSession(payload={"error": "no results"})
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    assert resp.total_results == 0


def test_web_search_http_401():
    """HTTP 401 → success=False, error_code=auth_fail。"""
    session = _FakeSession(status=401, payload={"error": "invalid key"})
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is False
    assert resp.error_code == ErrorCode.AUTH_FAIL.value


def test_chat_completion_still_uses_chat_completions_endpoint():
    """防回归：_chat_completion 仍走 /chat/completions，不走 /web_search。"""
    adapter = GLMSearchAdapter(api_key=TEST_KEY)

    captured_url = {}

    async def mock_post(url, payload, headers):
        captured_url["url"] = url
        return 200, {"choices": [{"message": {"content": "{}"}}]}

    adapter._post = mock_post
    asyncio.run(adapter._chat_completion([{"role": "user", "content": "hi"}]))

    assert captured_url["url"] == GLMSearchAdapter.CHAT_COMPLETIONS_ENDPOINT
    assert captured_url["url"] != GLMSearchAdapter.WEB_SEARCH_ENDPOINT
