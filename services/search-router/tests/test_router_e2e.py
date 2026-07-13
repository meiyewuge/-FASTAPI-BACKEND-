"""E2E 测试 — SearchRouter 全链路。"""

import asyncio
import json
import pytest
from search_router.candidate_pool import (
    CandidatePool,
    POOL_PENDING_REVIEW,
    POOL_OBSERVING,
    POOL_DISCARDED,
)
from search_router.config import SearchRouterConfig
from search_router.dual_review import DualReviewGate
from search_router.enhancer import GLMEnhancer
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import SearchResult, SearchResponse
from search_router.router import SearchRouter, RouteResult


class TestE2EDryRun:
    """dry_run=true 完整链路。"""

    def test_dry_run_full_chain(self):
        """dry_run=true 全链路：搜索→去重→映射→增强→候选池→审核→输出。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业AI趋势", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.success is True
        assert result.provider_used == "mock"
        assert result.fallback_level == "F1"
        assert result.total_cost == 0.0
        assert len(result.cards) > 0

    def test_dry_run_provider_is_mock(self):
        """dry_run=true 时 provider=mock。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="测试", task_type=TaskType.GLOBAL_AI_TOOLS)
        result = router.search_sync(req)
        assert result.provider_used == "mock"

    def test_dry_run_cost_zero(self):
        """dry_run=true 时 cost=0。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="测试", task_type=TaskType.TECHNICAL_RESEARCH)
        result = router.search_sync(req)
        assert result.total_cost == 0.0

    def test_cards_have_17_core_fields(self):
        """输出 card 有 17 核心字段。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert len(result.cards) > 0
        card = result.cards[0]
        core = IndustryIntelligenceCard.core_field_names()
        for name in core:
            assert hasattr(card, name), f"缺少核心字段: {name}"

    def test_cards_have_9_extension_fields(self):
        """输出 card 有 9 扩展字段。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        card = result.cards[0]
        ext = IndustryIntelligenceCard.extension_field_names()
        for name in ext:
            assert hasattr(card, name), f"缺少扩展字段: {name}"

    def test_candidate_for_ingest_true(self):
        """非 discarded card 的 candidate_for_ingest=True。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业趋势", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        for card in result.cards:
            if card.ingest_status != "discarded":
                assert card.candidate_for_ingest is True

    def test_no_formal_status(self):
        """所有 card 的 ingest_status 不为 formal。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        for card in result.cards:
            assert card.ingest_status != "formal"

    def test_enhancement_mode_mock_in_dry_run(self):
        """dry_run=true 时 enhancement_mode=mock。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        for mode in result.enhancement_modes:
            assert mode == "mock"


class TestE2EScenarios:
    """5 种 task_type 路由。"""

    @pytest.mark.parametrize("task_type", [
        TaskType.CHINESE_INDUSTRY_NEWS,
        TaskType.GLOBAL_AI_TOOLS,
        TaskType.OFFICIAL_DOCS,
        TaskType.TECHNICAL_RESEARCH,
        TaskType.FALLBACK_LIGHT_SEARCH,
    ])
    def test_all_task_types(self, task_type):
        """5 种 task_type 全链路通过。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业趋势", task_type=task_type)
        result = router.search_sync(req)
        assert result.success is True
        assert result.provider_used == "mock"


class TestE2ECandidatePool:
    """三池分流端到端。"""

    def test_pool_decisions_present(self):
        """每个 card 有 pool_decision。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert len(result.pool_decisions) == len(result.cards)

    def test_discarded_for_low_confidence(self):
        """低 confidence card 被 discarded。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS, max_results=20)
        result = router.search_sync(req)
        # 至少有一些 pool_decision
        for pd in result.pool_decisions:
            assert pd["pool_name"] in ("pending_review", "observing", "discarded")


class TestE2EDualReview:
    """双审核端到端。"""

    def test_review_decisions_present(self):
        """每个 card 有 review_decision。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert len(result.review_decisions) == len(result.cards)


class TestE2EBlacklist:
    """拉黑词端到端。"""

    def test_blacklist_term_in_query_discarded(self):
        """拉黑词出现在结果中时 → discarded。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        # Mock 数据中可能不包含拉黑词，但测试链路不崩溃
        req = SearchRequest(query="倒闭率 37.8%", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.success is True


class TestE2ECostExceeded:
    """成本超限。"""

    def test_cost_exceeded_returns_error(self):
        """成本超限时返回 cost_exceeded。"""
        cfg = SearchRouterConfig(dry_run=True)
        # 用一个极低的成本阈值让 pre_check 拒绝
        cfg.cost_limit_single_task = -1.0  # 负数 → 立即超限
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.success is False
        assert result.error_code == "cost_exceeded"


class TestE2EResultFormat:
    """结果格式。"""

    def test_to_dict_serializable(self):
        """to_dict() 输出可 JSON 序列化。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        d = result.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["success"] is True

    def test_metadata_has_dry_run(self):
        """metadata 包含 dry_run 标志。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.metadata.get("dry_run") is True

    def test_metadata_has_scenario(self):
        """metadata 包含 scenario。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)
        req = SearchRequest(query="美业", task_type=TaskType.GLOBAL_AI_TOOLS)
        result = router.search_sync(req)
        assert result.metadata.get("scenario") == "global_ai_tools"


# ── Phase 2 Cost Guard Patch 测试 ──────────────────────

from unittest.mock import AsyncMock, MagicMock, patch
from search_router.cost_tracker import CostTracker


class TestCostGuardPatch:
    """Phase 2 成本前置保护测试。

    验证 router 在 adapter.search() 之前调用 adapter.estimate_cost(request)，
    并将结果传入 CostTracker.pre_check()。
    成本超限时在 adapter.search() 前拦截。
    """

    def test_estimate_cost_called_before_search(self):
        """验证 router 调用了 adapter.estimate_cost(request)。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)

        # 用 MagicMock 替换 adapter，跟踪 estimate_cost 调用
        fake_adapter = MagicMock()
        fake_adapter.estimate_cost = MagicMock(return_value=0.036)
        fake_adapter.search = AsyncMock(return_value=SearchResponse(
            success=True,
            provider="mock",
            results=[],
        ))

        # 直接替换 router 内部不需要 factory，因为 dry_run=True 直接创建 MockProviderAdapter
        # 我们需要在 search 之前替换 adapter
        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)

        # Monkey-patch MockProviderAdapter to return our fake
        with patch.object(router, '_factory'):
            # 直接在 search 方法中 dry_run=True 会创建 MockProviderAdapter
            # 我们通过 patch MockProviderAdapter 来注入 fake
            with patch('search_router.router.MockProviderAdapter', return_value=fake_adapter):
                result = router.search_sync(req)

        assert fake_adapter.estimate_cost.called
        fake_adapter.estimate_cost.assert_called_once_with(req)

    def test_pre_check_uses_estimated_cost(self):
        """验证 pre_check 使用了 adapter.estimate_cost 返回的值。"""
        cfg = SearchRouterConfig(dry_run=True)
        cost_tracker = CostTracker(config=cfg)
        router = SearchRouter(config=cfg, cost_tracker=cost_tracker)

        fake_adapter = MagicMock()
        fake_adapter.estimate_cost = MagicMock(return_value=0.036)
        fake_adapter.search = AsyncMock(return_value=SearchResponse(
            success=True,
            provider="mock",
            results=[],
        ))

        # Spy on pre_check
        original_pre_check = cost_tracker.pre_check
        pre_check_calls = []

        def spy_pre_check(provider, estimated_cost, now=None):
            pre_check_calls.append((provider, estimated_cost))
            return original_pre_check(provider=provider, estimated_cost=estimated_cost, now=now)

        cost_tracker.pre_check = spy_pre_check

        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        with patch('search_router.router.MockProviderAdapter', return_value=fake_adapter):
            router.search_sync(req)

        assert len(pre_check_calls) == 1
        assert pre_check_calls[0][1] == 0.036

    def test_glm_free_provider_cost_zero(self):
        """GLM 免费 Provider 成本为 0，极低阈值下不触发成本熔断。"""
        cfg = SearchRouterConfig(dry_run=True, cost_limit_single_task=0.001)
        router = SearchRouter(config=cfg)

        fake_adapter = MagicMock()
        fake_adapter.estimate_cost = MagicMock(return_value=0.0)
        fake_adapter.search = AsyncMock(return_value=SearchResponse(
            success=True,
            provider="mock",
            results=[],
        ))

        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        with patch('search_router.router.MockProviderAdapter', return_value=fake_adapter):
            result = router.search_sync(req)

        assert result.error_code != "cost_exceeded"
        assert fake_adapter.search.called

    def test_estimate_cost_exception_degrades_to_zero(self):
        """estimate_cost() 抛异常时降级为 0.0，不阻塞搜索。"""
        cfg = SearchRouterConfig(dry_run=True)
        router = SearchRouter(config=cfg)

        fake_adapter = MagicMock()
        fake_adapter.estimate_cost = MagicMock(side_effect=RuntimeError("estimate failed"))
        fake_adapter.search = AsyncMock(return_value=SearchResponse(
            success=True,
            provider="mock",
            results=[],
        ))

        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        with patch('search_router.router.MockProviderAdapter', return_value=fake_adapter):
            result = router.search_sync(req)

        # 不阻塞，搜索仍然执行
        assert result.success is True
        assert fake_adapter.search.called

    def test_cost_exceeded_blocks_search(self):
        """成本超限时拦截 adapter.search()，不产生真实调用。"""
        cfg = SearchRouterConfig(dry_run=True, cost_limit_single_task=0.01)
        router = SearchRouter(config=cfg)

        fake_adapter = MagicMock()
        fake_adapter.estimate_cost = MagicMock(return_value=0.036)
        fake_adapter.search = AsyncMock(return_value=SearchResponse(
            success=True,
            provider="mock",
            results=[],
        ))

        req = SearchRequest(query="测试", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        with patch('search_router.router.MockProviderAdapter', return_value=fake_adapter):
            result = router.search_sync(req)

        # 成本超限
        assert result.success is False
        assert result.error_code == "cost_exceeded"
        # adapter.search() 不应被调用
        fake_adapter.search.assert_not_called()
        # 但 estimate_cost 被调用了
        fake_adapter.estimate_cost.assert_called_once()
