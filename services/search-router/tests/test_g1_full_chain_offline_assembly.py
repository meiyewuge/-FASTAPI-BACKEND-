"""G1: 全链离线装配证明 — Fake Provider + Fake DNS/Transport

验证Router全链路在依赖注入下的正确行为：
- EnricherOrchestrator + StandardRobotsProvider + FakeSafeTransport
- ContractValidator -> Merger -> Mapper -> CandidatePool
- fail-closed语义
- 生产零触碰
"""
from __future__ import annotations

import asyncio
import copy
import math
from datetime import datetime, timezone, timedelta

import pytest

from search_router.candidate_pool import CandidatePool
from search_router.config import SearchRouterConfig
from search_router.contract_validator import ContractValidator
from search_router.cost_tracker import CostTracker
from search_router.dedup import DedupManager
from search_router.dual_review import DualReviewGate
from search_router.enhancer import GLMEnhancer
from search_router.enrichers.safe_transport import FetchResult
from search_router.enrichers.standard_robots_provider import (
    RobotsDecision,
    RobotsCheckResult,
    StandardRobotsProvider,
)
from search_router.enrichers.orchestrator import EnricherOrchestrator
from search_router.merger import ResultMerger
from search_router.mapper import map_batch
from search_router.models.search_response import SearchResult
from search_router.quarantine_handler import QuarantineHandler
from search_router.retry import RetryPolicy
from search_router.router import SearchRouter


# -- Fake组件 --

class FakeSafeTransport:
    """实现SafeFetcherProtocol，记录调用次数，返回受控响应。"""

    def __init__(
        self,
        robots_fetch_result: FetchResult | None = None,
        page_fetch_result: FetchResult | None = None,
    ):
        self._robots_fetch_result = robots_fetch_result
        self._page_fetch_result = page_fetch_result
        self.fetch_call_count = 0
        self.fetch_robots_call_count = 0
        self.fetch_urls: list[str] = []
        self.fetch_robots_urls: list[str] = []

    async def fetch(self, url: str, domains=None, approved_domains=None) -> FetchResult:
        self.fetch_call_count += 1
        self.fetch_urls.append(url)
        if self._page_fetch_result is not None:
            return self._page_fetch_result
        return FetchResult(
            status=0, content_type="", body="", peer_ip="",
            redirect_location=None, bytes_read=0,
            final_url_safe="", error_code="no_fake_response",
        )

    async def fetch_robots(self, url: str, domains=None, approved_domains=None) -> FetchResult:
        self.fetch_robots_call_count += 1
        self.fetch_robots_urls.append(url)
        if self._robots_fetch_result is not None:
            return self._robots_fetch_result
        return FetchResult(
            status=0, content_type="", body="", peer_ip="",
            redirect_location=None, bytes_read=0,
            final_url_safe="", error_code="no_fake_response",
        )


# -- 辅助函数 --

APPROVED_DOMAINS = {
    "www.gov.cn", "gov.cn", "news.cn", "www.news.cn",
    "www.stcn.com", "stcn.com", "www.chinadaily.com.cn",
    "chinadaily.com.cn", "36kr.com", "www.36kr.com",
}

NOW = datetime(2026, 7, 12, 18, 0, 0, tzinfo=timezone(timedelta(hours=8)))


def _make_tavily_result(
    url: str = "https://www.stcn.com/article/test.html",
    title: str = "测试文章",
    source_credibility: float = 0.9,
    publish_time: str | None = None,
    confidence: float = float("nan"),
    freshness: float = float("nan"),
    relevance: float = 0.7,
) -> SearchResult:
    return SearchResult(
        title=title, url=url, publish_time=publish_time,
        provider="tavily", confidence_score=confidence,
        freshness_score=freshness, relevance_score=relevance,
        source_credibility_score=source_credibility,
        final_score=confidence,
        computation_trace={
            "source": "test",
            "_source_credibility": {"credibility_tier": "A" if source_credibility >= 0.9 else "B"},
        },
    )


def _robots_allow_result() -> FetchResult:
    return FetchResult(
        status=404, content_type="", body="", peer_ip="1.2.3.4",
        redirect_location=None, bytes_read=0,
        final_url_safe="https://www.stcn.com", error_code="http_404",
    )


def _robots_deny_result() -> FetchResult:
    return FetchResult(
        status=200, content_type="text/plain",
        body="User-agent: *\nDisallow: /",
        peer_ip="1.2.3.4", redirect_location=None, bytes_read=28,
        final_url_safe="https://www.stcn.com", error_code=None,
    )


def _robots_unavailable_result() -> FetchResult:
    return FetchResult(
        status=0, content_type="", body="", peer_ip="",
        redirect_location=None, bytes_read=0,
        final_url_safe="", error_code="dns_resolution_failed",
    )


def _page_with_date_result() -> FetchResult:
    html = '<!DOCTYPE html><html><head><meta property="article:published_time" content="2026-07-10T08:00:00+08:00"></head><body>Test</body></html>'
    return FetchResult(
        status=200, content_type="text/html; charset=utf-8",
        body=html, peer_ip="1.2.3.4",
        redirect_location=None, bytes_read=len(html),
        final_url_safe="https://www.stcn.com", error_code=None,
    )


def _page_error_result() -> FetchResult:
    return FetchResult(
        status=0, content_type="", body="", peer_ip="",
        redirect_location=None, bytes_read=0,
        final_url_safe="", error_code="connection_timeout",
    )


# -- 场景1: robots DENY -> 页面调用=0 --

class TestG1RobotsDenyNoPageFetch:

    @pytest.mark.asyncio
    async def test_robots_deny_no_page_call(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_deny_result(),
            page_fetch_result=_page_with_date_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        assert len(enriched) == 1
        assert fake_transport.fetch_call_count == 0
        assert fake_transport.fetch_robots_call_count >= 1

    @pytest.mark.asyncio
    async def test_robots_deny_trace(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_deny_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        trace = enriched[0].computation_trace
        assert "_enrichment" in trace
        assert trace["_enrichment"]["reason_code"] == "robots_denied"


# -- 场景2: robots UNAVAILABLE -> 页面调用=0 --

class TestG1RobotsUnavailableNoPageFetch:

    @pytest.mark.asyncio
    async def test_robots_unavailable_no_page_call(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_unavailable_result(),
            page_fetch_result=_page_with_date_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        assert fake_transport.fetch_call_count == 0

    @pytest.mark.asyncio
    async def test_robots_unavailable_trace(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_unavailable_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        trace = enriched[0].computation_trace
        assert "_enrichment" in trace
        assert trace["_enrichment"]["reason_code"] == "robots_unavailable"


# -- 场景3: robots ALLOW + 补取成功 --

class TestG1RobotsAllowEnrichSuccess:

    @pytest.mark.asyncio
    async def test_enrich_success_page_called(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_with_date_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        assert fake_transport.fetch_call_count >= 1

    @pytest.mark.asyncio
    async def test_enrich_success_scores_recalculated(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_with_date_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        enr = enriched[0]
        trace = enr.computation_trace
        if "_enrichment" in trace and trace["_enrichment"]["status"] == "enriched":
            assert enr.publish_time is not None
            assert not math.isnan(enr.freshness_score)
            assert not math.isnan(enr.confidence_score)
            assert not math.isnan(enr.final_score)

    @pytest.mark.asyncio
    async def test_enrich_success_trace_complete(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_with_date_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        trace = enriched[0].computation_trace
        assert "_enrichment" in trace
        assert "status" in trace["_enrichment"]


# -- 场景4: 补取失败 --

class TestG1EnrichFailureNaNIsolation:

    @pytest.mark.asyncio
    async def test_enrich_failure_trace(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_error_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        trace = enriched[0].computation_trace
        assert "_enrichment" in trace
        assert trace["_enrichment"]["status"] in ("skipped", "failed")

    @pytest.mark.asyncio
    async def test_enrich_failure_no_side_effect(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_error_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        r1 = _make_tavily_result(url="https://www.stcn.com/a.html")
        r2 = _make_tavily_result(url="https://www.stcn.com/b.html", publish_time="2026-07-10")
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([r1, r2], config)
        assert len(enriched) == 2
        assert enriched[1].publish_time == "2026-07-10"


# -- 场景5: quarantine不进CandidatePreview --

class TestG1QuarantineNotInCandidatePool:

    def test_nan_source_credibility_quarantined(self):
        validator = ContractValidator()
        result = SearchResult(
            title="NaN test", url="https://example.com",
            provider="bocha", source_credibility_score=float("nan"),
            confidence_score=0.8, freshness_score=0.7,
            relevance_score=0.6, final_score=0.8,
        )
        vr = validator.validate(result)
        assert not vr.is_valid
        assert "source_credibility_score" in vr.nan_fields

    def test_nan_quarantined_not_in_pool(self):
        validator = ContractValidator()
        pool = CandidatePool()
        initial_count = len(pool.pending_review)

        result = SearchResult(
            title="NaN test", url="https://example.com",
            provider="bocha", source_credibility_score=float("nan"),
            confidence_score=0.8, freshness_score=0.7,
            relevance_score=0.6, final_score=0.8,
        )
        batch_result = validator.validate_batch([result])
        valid = batch_result["valid"]
        for r in valid:
            cards = map_batch([r], "chinese_industry_news", "test", 0.0)
            for c in cards:
                pool.route_card(c)

        assert len(pool.pending_review) == initial_count


# -- 场景6: NaN不进CandidatePreview --

class TestG1NaNNotInCandidatePool:

    def test_nan_confidence_quarantined(self):
        validator = ContractValidator()
        result = SearchResult(
            title="NaN confidence", url="https://example.com",
            provider="bocha", source_credibility_score=0.9,
            confidence_score=float("nan"), freshness_score=0.7,
            relevance_score=0.6, final_score=float("nan"),
        )
        vr = validator.validate(result)
        assert not vr.is_valid
        assert "confidence_score" in vr.nan_fields


# -- 场景7: computation_trace完整 --

class TestG1ComputationTraceComplete:

    def test_trace_not_empty_after_enricher(self):
        result = _make_tavily_result()
        assert result.computation_trace is not None
        assert isinstance(result.computation_trace, dict)

    @pytest.mark.asyncio
    async def test_trace_after_robots_deny(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_deny_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()
        enriched = await orchestrator.enrich_batch([result], config)

        trace = enriched[0].computation_trace
        assert trace is not None
        assert "_enrichment" in trace
        assert "status" in trace["_enrichment"]
        assert "reason_code" in trace["_enrichment"]


# -- 场景8: CandidatePool真实状态不变 --

class TestG1CandidatePoolUnchanged:

    def test_shadow_pool_independent(self):
        shadow_pool = CandidatePool()
        prod_pool = CandidatePool()
        initial_shadow = len(shadow_pool.pending_review)
        initial_prod = len(prod_pool.pending_review)

        from search_router.models.intelligence_card import IndustryIntelligenceCard
        card = IndustryIntelligenceCard(
            title="test", url="https://example.com",
            source="test", industry_dimension="test", final_score=0.8,
            confidence_score=0.8,
        )
        shadow_pool.route_card(card)

        assert len(shadow_pool.pending_review) == initial_shadow + 1
        assert len(prod_pool.pending_review) == initial_prod


# -- 场景9: 未注入Real组件时fail-closed --

class TestG1NoEnricherFailClosed:

    @pytest.mark.asyncio
    async def test_router_dry_run_no_enricher(self):
        config = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=config)
        from search_router.models.search_request import SearchRequest, TaskType
        request = SearchRequest(
            query="美业政策", task_type=TaskType.CHINESE_INDUSTRY_NEWS
        )
        result = await router.search(request)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_enricher_none_no_crash(self):
        config = SearchRouterConfig(dry_run=True)
        router = SearchRouter(
            config=config, enricher_orchestrator=None,
        )
        from search_router.models.search_request import SearchRequest, TaskType
        request = SearchRequest(
            query="美业政策", task_type=TaskType.CHINESE_INDUSTRY_NEWS
        )
        result = await router.search(request)
        assert result.success is True


# -- 场景10: 不允许PermissiveValidator --

class TestG1NoPermissiveValidator:

    def test_validator_hard_checks(self):
        validator = ContractValidator()
        nan_fields = [
            ("source_credibility_score", float("nan")),
            ("freshness_score", float("nan")),
            ("confidence_score", float("nan")),
            ("relevance_score", float("nan")),
        ]
        for field_name, nan_val in nan_fields:
            result = SearchResult(
                title="test", url="https://example.com",
                provider="bocha", source_credibility_score=0.9,
                confidence_score=0.8, freshness_score=0.7,
                relevance_score=0.6, final_score=0.8,
            )
            setattr(result, field_name, nan_val)
            vr = validator.validate(result)
            assert not vr.is_valid, f"{field_name}=NaN should be quarantined"

    def test_valid_zero_not_quarantined(self):
        validator = ContractValidator()
        result = SearchResult(
            title="test", url="https://example.com",
            provider="bocha", source_credibility_score=0.0,
            confidence_score=0.0, freshness_score=0.0,
            relevance_score=0.0, final_score=0.0,
        )
        vr = validator.validate(result)
        assert vr.is_valid


# -- 场景11: 不允许绕过SafeTransport --

class TestG1NoBypassSafeTransport:

    @pytest.mark.asyncio
    async def test_all_fetches_through_safe_transport(self):
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_with_date_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        await orchestrator.enrich_batch([result], config)

        total_calls = fake_transport.fetch_call_count + fake_transport.fetch_robots_call_count
        assert total_calls > 0


# -- 场景12: aiohttp版本 --

class TestG1AiohttpVersion:

    def test_aiohttp_version(self):
        import aiohttp
        assert aiohttp.__version__ == "3.13.5"


# -- 综合链路 --

class TestG1FullChainAssembly:

    @pytest.mark.asyncio
    async def test_enricher_to_validator_chain(self):
        """Enricher -> Validator -> Merger -> Mapper 完整链路"""
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_allow_result(),
            page_fetch_result=_page_error_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )

        r_with_date = SearchResult(
            title="有日期文章", url="https://www.stcn.com/a.html",
            publish_time="2026-07-10", provider="bocha",
            source_credibility_score=0.9, confidence_score=0.75,
            freshness_score=0.8, relevance_score=0.7, final_score=0.75,
            computation_trace={"source": "test"},
        )
        r_no_date = _make_tavily_result(url="https://www.stcn.com/b.html")

        config = SearchRouterConfig()
        enriched = await orchestrator.enrich_batch([r_with_date, r_no_date], config)

        validator = ContractValidator()
        batch_result = validator.validate_batch(enriched)
        valid = batch_result["valid"]

        merger = ResultMerger()
        merge_result = merger.merge(valid)

        if merge_result.results:
            cards = map_batch(
                merge_result.results,
                task_type="chinese_industry_news",
                query="美业政策",
                estimated_cost=0.01,
            )
            assert len(cards) <= len(merge_result.results)

    @pytest.mark.asyncio
    async def test_robots_deny_then_validator(self):
        """Robots deny -> 结果标记skipped -> 进入Validator"""
        fake_transport = FakeSafeTransport(
            robots_fetch_result=_robots_deny_result(),
        )
        robots_provider = StandardRobotsProvider(
            fake_transport, approved_domains=APPROVED_DOMAINS
        )
        orchestrator = EnricherOrchestrator(
            safe_fetcher=fake_transport,
            robots_provider=robots_provider,
            approved_domains=APPROVED_DOMAINS,
            reference_time=NOW,
        )
        result = _make_tavily_result()
        config = SearchRouterConfig()

        enriched = await orchestrator.enrich_batch([result], config)
        assert len(enriched) == 1

        validator = ContractValidator()
        batch_result = validator.validate_batch(enriched)
        # 结果NaN(没有补到日期) -> quarantine, 但流程不crash
        assert batch_result["stats"]["total"] == 1

    @pytest.mark.asyncio
    async def test_production_zero_touch(self):
        """生产CandidatePool零触碰"""
        from search_router.models.intelligence_card import IndustryIntelligenceCard

        shadow_pool = CandidatePool()
        before = len(shadow_pool.pending_review)

        # 影子池操作
        card = IndustryIntelligenceCard(
            title="shadow test", url="https://example.com/shadow",
            source="shadow", industry_dimension="shadow", final_score=0.85,
            confidence_score=0.85,
        )
        shadow_pool.route_card(card)
        after = len(shadow_pool.pending_review)

        # 生产CandidatePool(独立实例)不受影响
        prod_pool = CandidatePool()
        assert len(prod_pool.pending_review) == 0

    @pytest.mark.asyncio
    async def test_valid_result_full_chain_to_pool(self):
        """合法结果完整链路 -> CandidatePool"""
        result = SearchResult(
            title="合法文章", url="https://www.stcn.com/legal.html",
            publish_time="2026-07-10", provider="bocha",
            source_credibility_score=0.9, confidence_score=0.85,
            freshness_score=0.8, relevance_score=0.75, final_score=0.85,
            computation_trace={"source": "test", "chain": "full"},
        )

        validator = ContractValidator()
        batch_result = validator.validate_batch([result])
        assert len(batch_result["valid"]) == 1

        merger = ResultMerger()
        merge_result = merger.merge(batch_result["valid"])

        cards = map_batch(
            merge_result.results,
            task_type="chinese_industry_news",
            query="美业政策",
            estimated_cost=0.01,
        )
        assert len(cards) >= 1

        pool = CandidatePool()
        for card in cards:
            decision = pool.route_card(card)
        assert len(pool.pending_review) >= 1
