"""Mock Contract 专项测试 — V1.1。

验证 Mock Adapter 返回的 SearchResult 遵守正式评分契约：
- 所有 score 字段非 NaN
- final_score = confidence_score
- 权重 0.45/0.25/0.30
- 不调用 Scorer 网络或 Provider
- fixture_mode=mock_contract_valid 标记
"""

import math
import pytest
from search_router.adapters.mock import MockProviderAdapter, _mock_compute_scores, MOCK_DEFAULT_SCORES
from search_router.models.search_request import SearchRequest, TaskType
from search_router.contract_validator import ContractValidator


class TestMockContractScores:
    """Mock 结果评分契约测试。"""

    @pytest.mark.parametrize("task_type", [
        TaskType.CHINESE_INDUSTRY_NEWS,
        TaskType.GLOBAL_AI_TOOLS,
        TaskType.OFFICIAL_DOCS,
        TaskType.TECHNICAL_RESEARCH,
        TaskType.FALLBACK_LIGHT_SEARCH,
    ])
    @pytest.mark.asyncio
    async def test_all_task_types_scores_non_nan(self, task_type):
        """每种 task_type 的 Mock 结果全部 score 非 NaN。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="测试", task_type=task_type)
        resp = await adapter.search(req)
        assert resp.success is True
        assert len(resp.results) > 0
        for r in resp.results:
            assert not math.isnan(r.source_credibility_score), f"source_credibility NaN for {r.url}"
            assert not math.isnan(r.freshness_score), f"freshness NaN for {r.url}"
            assert not math.isnan(r.relevance_score), f"relevance NaN for {r.url}"
            assert not math.isnan(r.confidence_score), f"confidence NaN for {r.url}"
            assert not math.isnan(r.final_score), f"final_score NaN for {r.url}"

    @pytest.mark.asyncio
    async def test_final_score_equals_confidence(self):
        """final_score = confidence_score（与真实 Adapter 一致）。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="美业AI趋势", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        for r in resp.results:
            assert r.final_score == r.confidence_score, f"final={r.final_score} != confidence={r.confidence_score}"

    @pytest.mark.asyncio
    async def test_confidence_formula_correct(self):
        """confidence = 0.45*src_cred + 0.25*fresh + 0.30*rel。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="美业AI趋势", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        for r in resp.results:
            expected = 0.45 * r.source_credibility_score + 0.25 * r.freshness_score + 0.30 * r.relevance_score
            expected = max(0.0, min(1.0, expected))
            assert abs(r.confidence_score - expected) < 0.001, f"confidence={r.confidence_score:.4f} != expected={expected:.4f}"

    @pytest.mark.asyncio
    async def test_scores_in_valid_range(self):
        """所有 score 在 [0.0, 1.0] 范围内。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        for r in resp.results:
            for field_name in ["source_credibility_score", "freshness_score", "relevance_score", "confidence_score", "final_score"]:
                val = getattr(r, field_name)
                assert 0.0 <= val <= 1.0, f"{field_name}={val} out of [0,1] for {r.url}"

    @pytest.mark.asyncio
    async def test_computation_trace_fixture_mode(self):
        """computation_trace 包含 fixture_mode=mock_contract_valid。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        for r in resp.results:
            assert r.computation_trace.get("fixture_mode") == "mock_contract_valid", f"missing fixture_mode in trace for {r.url}"

    @pytest.mark.asyncio
    async def test_computation_trace_weights(self):
        """computation_trace 包含正确的权重。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        for r in resp.results:
            weights = r.computation_trace.get("weights", {})
            assert abs(weights.get("source_credibility", 0) - 0.45) < 0.001
            assert abs(weights.get("freshness", 0) - 0.25) < 0.001
            assert abs(weights.get("relevance", 0) - 0.30) < 0.001

    @pytest.mark.asyncio
    async def test_provider_is_mock(self):
        """provider 仍为 mock，不调用任何真实 Provider。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="测试", task_type=TaskType.GLOBAL_AI_TOOLS)
        resp = await adapter.search(req)
        for r in resp.results:
            assert r.provider == "mock"

    @pytest.mark.asyncio
    async def test_cost_zero(self):
        """Mock 成本为 0。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        assert resp.credits_used == 0
        assert resp.estimated_cost == 0.0


class TestMockContractValidatorIntegration:
    """Mock 结果通过真实 ContractValidator 闸门。"""

    @pytest.mark.asyncio
    async def test_all_mock_results_pass_validator(self):
        """Mock 返回的结果全部通过 ContractValidator。"""
        adapter = MockProviderAdapter()
        req = SearchRequest(query="美业AI趋势", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        resp = await adapter.search(req)
        validator = ContractValidator()
        batch_result = validator.validate_batch(resp.results)
        assert len(batch_result["quarantined"]) == 0, f"Mock结果被隔离: {[(r.title, vr.quarantine_reason) for r, vr in batch_result['quarantined']]}"
        assert len(batch_result["valid"]) == len(resp.results)

    @pytest.mark.asyncio
    async def test_mock_default_dry_run_no_quarantine(self):
        """默认 dry-run 路由不产生 quarantine。"""
        from search_router.config import SearchRouterConfig
        from search_router.router import SearchRouter
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业AI趋势", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = await router.search(req)
        assert result.success is True
        assert result.quarantine_stats.get("total_quarantined", 0) == 0
        assert result.quarantine_stats.get("total_valid", 0) > 0
        assert len(result.cards) > 0

    @pytest.mark.asyncio
    async def test_gov_domain_gets_high_credibility(self):
        """gov.cn 域名获得 A 级 0.9 可信度。"""
        scores = _mock_compute_scores("https://www.nmpa.gov.cn/xxgk/test.html")
        assert scores["source_credibility_score"] == 0.9

    @pytest.mark.asyncio
    async def test_douyin_domain_gets_d_credibility(self):
        """douyin.com 域名获得 D 级 0.4 可信度。"""
        scores = _mock_compute_scores("https://www.douyin.com/topic/test")
        assert scores["source_credibility_score"] == 0.4

    @pytest.mark.asyncio
    async def test_unknown_domain_gets_default_credibility(self):
        """未识别域名获得默认 C 级 0.55 可信度。"""
        scores = _mock_compute_scores("https://unknown-example.com/page")
        assert scores["source_credibility_score"] == 0.55


class TestMockContractDeterminism:
    """Mock 评分确定性测试。"""

    def test_same_url_same_scores(self):
        """相同 URL 多次调用返回完全相同的评分。"""
        url = "https://www.beauty-industry.cn/trends/test"
        s1 = _mock_compute_scores(url)
        s2 = _mock_compute_scores(url)
        for key in ["source_credibility_score", "freshness_score", "relevance_score", "confidence_score", "final_score"]:
            assert s1[key] == s2[key], f"Non-deterministic: {key} differs"

    def test_different_urls_may_differ_only_in_credibility(self):
        """不同 URL 只有 source_credibility 可能不同（域名差异）。"""
        s1 = _mock_compute_scores("https://www.nmpa.gov.cn/test")
        s2 = _mock_compute_scores("https://www.douyin.com/test")
        assert s1["freshness_score"] == s2["freshness_score"]
        assert s1["relevance_score"] == s2["relevance_score"]
        assert s1["source_credibility_score"] != s2["source_credibility_score"]
        assert s1["confidence_score"] != s2["confidence_score"]
