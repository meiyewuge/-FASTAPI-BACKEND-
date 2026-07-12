"""Phase1 Adapter Scoring Contract Tests.

验证3个Adapter的Phase1评分链:
  - Bocha (PRIMARY): 五字段评分 + computation_trace九字段
  - Tavily (PRIMARY): tanh规范化 + 五字段评分
  - GLM (FALLBACK): 无hardcoded 0.75 + 五字段评分

权重: source_credibility=0.45, freshness=0.25, relevance=0.30
NaN规则: 未识别信源→NaN; 无发布日期→NaN; NaN不伪装成0.0

本测试为LOCAL_PRECHECK, 最终测试由扣子在ECS影子目录执行。
"""
import asyncio
import ast
import inspect
import math
import os

import pytest

from search_router.adapters.bocha import BochaAdapter
from search_router.adapters.tavily import TavilyAdapter
from search_router.adapters.glm_search import GLMSearchAdapter
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import ProviderType


TEST_KEY = "test_key_xxx"


# ── Mock Session (matches existing adapter test pattern) ──

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
    async def text(self):
        return str(self._payload)

class _FakeSession:
    """模拟 aiohttp.ClientSession, 绝不联网。"""
    def __init__(self, status=200, payload=None):
        self._status = status
        self._payload = payload if payload is not None else {}
        self.calls = []
        self.closed = False
    def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append({"url": url, "json": json, "headers": headers, "kwargs": kwargs})
        return _FakeResp(self._status, self._payload)
    async def close(self):
        self.closed = True


def _req(**kw):
    kw.setdefault("query", "美业AI趋势")
    kw.setdefault("task_type", TaskType.CHINESE_INDUSTRY_NEWS)
    kw.setdefault("max_results", 5)
    kw.setdefault("time_range", "oneWeek")
    return SearchRequest(**kw)


# ── Fixtures ────────────────────────────────────────────

def _bocha_response():
    return {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "美业AI转型报告",
                        "url": "https://www.sohu.com/a/123",
                        "snippet": "美业数字化转型加速, AI技术驱动行业变革。" * 10,
                        "summary": "美业AI转型深度报道",
                        "siteName": "sohu.com",
                        "datePublished": "2026-07-01T10:00:00",
                    }
                ]
            }
        }
    }

def _bocha_response_no_date():
    return {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "无日期结果",
                        "url": "https://www.36kr.com/p/456",
                        "snippet": "内容但无发布日期",
                        "siteName": "36kr.com",
                        "datePublished": None,
                    }
                ]
            }
        }
    }

def _tavily_response():
    return {
        "results": [
            {
                "title": "AI Video Generation Trends",
                "url": "https://www.sohu.com/a/ai-video",
                "content": "AI video generation is transforming content creation." * 5,
                "source": "sohu.com",
                "score": 0.93,
                "published_date": "2026-06-15T12:00:00",
            }
        ]
    }

def _tavily_response_no_date():
    return {
        "results": [
            {
                "title": "No Date Article",
                "url": "https://www.36kr.com/p/456",
                "content": "Content without publish date",
                "source": "36kr.com",
                "score": 0.85,
                "published_date": None,
            }
        ]
    }

def _glm_response():
    return {
        "search_result": [
            {
                "title": "美业AI趋势",
                "content": "美业数字化转型内容",
                "link": "",
                "media": "",
                "publish_date": "2026-07-01",
                "refer": "ref_1",
            }
        ]
    }

def _glm_response_with_media():
    return {
        "search_result": [
            {
                "title": "GLM搜索结果",
                "content": "GLM Web Search API返回结果",
                "link": "",
                "media": "36kr.com",
                "publish_date": "2026-07-01",
                "refer": "ref_1",
            }
        ]
    }

def _glm_response_no_media():
    return {
        "search_result": [
            {
                "title": "无media结果",
                "content": "内容但无media",
                "link": "",
                "media": "",
                "publish_date": "2026-07-01",
                "refer": "ref_2",
            }
        ]
    }

def _glm_response_no_date():
    return {
        "search_result": [
            {
                "title": "无日期结果",
                "content": "内容但无日期",
                "link": "",
                "media": "sohu.com",
                "publish_date": None,
                "refer": "ref_3",
            }
        ]
    }


# ════════════════════════════════════════════════════════
# Bocha Tests
# ════════════════════════════════════════════════════════

def test_bocha_provider_type_primary():
    """Bocha provider_type = PRIMARY。"""
    adapter = BochaAdapter(api_key=TEST_KEY)
    assert adapter.provider_type == ProviderType.PRIMARY


def test_bocha_produces_five_scoring_fields():
    """Bocha正常fixture产生五字段评分。"""
    session = _FakeSession(payload=_bocha_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    r = resp.results[0]
    # 五字段必须存在
    assert hasattr(r, "source_credibility_score")
    assert hasattr(r, "freshness_score")
    assert hasattr(r, "relevance_score")
    assert hasattr(r, "confidence_score")
    assert hasattr(r, "computation_trace")
    # source_credibility 不为NaN (sohu.com是已知信源)
    assert not math.isnan(r.source_credibility_score)
    # freshness 不为NaN (有日期)
    assert not math.isnan(r.freshness_score)
    # relevance 不为NaN
    assert not math.isnan(r.relevance_score)
    # confidence 不为NaN
    assert not math.isnan(r.confidence_score)
    # final_score = confidence
    assert r.final_score == r.confidence_score


def test_bocha_no_date_freshness_nan():
    """Bocha无日期→freshness=NaN→confidence=NaN。"""
    session = _FakeSession(payload=_bocha_response_no_date())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    assert math.isnan(r.freshness_score)
    assert math.isnan(r.confidence_score)
    assert math.isnan(r.final_score)
    # source_credibility 不为NaN (36kr.com是已知信源)
    assert not math.isnan(r.source_credibility_score)


def test_bocha_computation_trace_nine_fields():
    """Bocha computation_trace九字段完整。"""
    session = _FakeSession(payload=_bocha_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    trace = resp.results[0].computation_trace
    required_fields = [
        "formula_version",
        "source_credibility_score",
        "freshness_score",
        "relevance_score",
        "weights",
        "confidence_score",
        "final_score",
        "provider",
        "quarantine_reason",
    ]
    for field in required_fields:
        assert field in trace, f"computation_trace missing field: {field}"


# ════════════════════════════════════════════════════════
# Tavily Tests
# ════════════════════════════════════════════════════════

def test_tavily_provider_type_primary():
    """Tavily provider_type = PRIMARY。"""
    adapter = TavilyAdapter(api_key=TEST_KEY)
    assert adapter.provider_type == ProviderType.PRIMARY


def test_tavily_relevance_tanh_normalized():
    """Tavily raw score经过tanh规范化。"""
    session = _FakeSession(payload=_tavily_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    # raw score = 0.93, tanh(0.93 * 1.5) ≈ 0.827
    expected = math.tanh(0.93 * 1.5)
    assert r.relevance_score == pytest.approx(expected, rel=1e-4)
    # relevance 不等于 raw score
    assert r.relevance_score != 0.93


def test_tavily_relevance_not_equal_confidence():
    """Tavily relevance不直接等于confidence。"""
    session = _FakeSession(payload=_tavily_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    assert r.relevance_score != r.confidence_score


def test_tavily_produces_five_scoring_fields():
    """Tavily正常fixture产生五字段评分。"""
    session = _FakeSession(payload=_tavily_response())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    r = resp.results[0]
    assert hasattr(r, "source_credibility_score")
    assert hasattr(r, "freshness_score")
    assert hasattr(r, "relevance_score")
    assert hasattr(r, "confidence_score")
    assert hasattr(r, "computation_trace")
    assert not math.isnan(r.source_credibility_score)
    assert not math.isnan(r.freshness_score)
    assert not math.isnan(r.relevance_score)
    assert not math.isnan(r.confidence_score)


def test_tavily_no_date_freshness_nan():
    """Tavily无日期→freshness=NaN→confidence=NaN。"""
    session = _FakeSession(payload=_tavily_response_no_date())
    adapter = TavilyAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    assert math.isnan(r.freshness_score)
    assert math.isnan(r.confidence_score)


# ════════════════════════════════════════════════════════
# GLM Tests
# ════════════════════════════════════════════════════════

def test_glm_provider_type_fallback():
    """GLM provider_type = FALLBACK。"""
    adapter = GLMSearchAdapter(api_key=TEST_KEY)
    assert adapter.provider_type == ProviderType.FALLBACK


def test_glm_no_hardcoded_075():
    """GLM可执行代码无confidence=0.75硬编码 (AST检查)。"""
    import search_router.adapters.glm_search as glm_module
    source = inspect.getsource(glm_module)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if abs(float(node.value) - 0.75) < 1e-9:
                pytest.fail(f"GLM adapter has hardcoded 0.75 at line {node.lineno}")


def test_glm_produces_five_scoring_fields():
    """GLM正常fixture产生五字段评分。"""
    session = _FakeSession(payload=_glm_response_with_media())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    assert resp.success is True
    r = resp.results[0]
    assert hasattr(r, "source_credibility_score")
    assert hasattr(r, "freshness_score")
    assert hasattr(r, "relevance_score")
    assert hasattr(r, "confidence_score")
    assert hasattr(r, "computation_trace")


def test_glm_no_media_source_credibility_nan():
    """GLM无media→source_credibility=NaN (glm_search不在已知信源)。"""
    session = _FakeSession(payload=_glm_response_no_media())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    # source = "glm_search", 不在已知信源列表 → NaN
    assert math.isnan(r.source_credibility_score)


def test_glm_no_date_freshness_nan():
    """GLM无日期→freshness=NaN。"""
    session = _FakeSession(payload=_glm_response_no_date())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    assert math.isnan(r.freshness_score)


def test_glm_computation_trace_complete():
    """GLM computation_trace完整 (九字段)。"""
    session = _FakeSession(payload=_glm_response_with_media())
    adapter = GLMSearchAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    trace = resp.results[0].computation_trace
    required_fields = [
        "formula_version",
        "source_credibility_score",
        "freshness_score",
        "relevance_score",
        "weights",
        "confidence_score",
        "final_score",
        "provider",
        "quarantine_reason",
    ]
    for field in required_fields:
        assert field in trace, f"GLM computation_trace missing: {field}"


# ════════════════════════════════════════════════════════
# 通用 Tests
# ════════════════════════════════════════════════════════

def test_confidence_formula_weights():
    """confidence公式精确为0.45/0.25/0.30。"""
    session = _FakeSession(payload=_bocha_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    trace = r.computation_trace
    weights = trace["weights"]
    assert weights["source_credibility"] == 0.45
    assert weights["freshness"] == 0.25
    assert weights["relevance"] == 0.30


def test_final_score_matches_confidence():
    """final_score符合批准契约 (= confidence)。"""
    session = _FakeSession(payload=_bocha_response())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    assert r.final_score == r.confidence_score


def test_nan_not_disguised_as_zero():
    """NaN结果不能伪装成0.0。"""
    session = _FakeSession(payload=_bocha_response_no_date())
    adapter = BochaAdapter(api_key=TEST_KEY, session=session)
    resp = asyncio.run(adapter.search(_req()))
    r = resp.results[0]
    assert math.isnan(r.freshness_score)
    assert r.freshness_score != 0.0
    assert math.isnan(r.confidence_score)
    assert r.confidence_score != 0.0
    assert math.isnan(r.final_score)
    assert r.final_score != 0.0
