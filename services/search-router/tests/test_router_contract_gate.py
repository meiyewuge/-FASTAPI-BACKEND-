"""Contract Gate 专项测试 — 验证 NaN 拦截闸门。

覆盖 WUYOU_SR_P02 施工规格书至少 16 项测试用例：
1. source_credibility NaN → quarantine
2. freshness NaN → quarantine
3. relevance NaN → quarantine
4. confidence NaN → quarantine
5. 合法 0.0 通过 Validator，再被 0.30 规则丢弃
6. 正常非 NaN 结果保持原链
7. 混合批次：valid 继续、NaN 隔离
8. 全部隔离：成本仍记录
9. 连续两次 search 统计不串批
10. quarantine 不进入 Merger
11. quarantine 不进入 CandidatePool
12. RouteResult.to_dict() 包含本批统计
13. Validator 异常整批 fail closed
14. Handler 异常整批 fail closed
15. 错误 metadata 不含异常原文
16. dry_run Mock 结果同样必须经过 Validator
"""

from __future__ import annotations

import asyncio
import math
import sys
import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 确保项目根目录在 sys.path ──────────────────────────
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── 直接导入真实类 ─────────────────────────────────────
from search_router.contract_validator import ContractValidator, ValidationResult
from search_router.quarantine_handler import QuarantineHandler, QuarantinedResult
from search_router.models.search_response import SearchResult, SearchResponse
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.candidate_pool import CandidatePool
from search_router.merger import ResultMerger, MergeResult
from search_router.dedup import DedupManager, DedupResult
from search_router.enhancer import GLMEnhancer, EnhancementResult
from search_router.dual_review import DualReviewGate, ReviewDecision
from search_router.cost_tracker import CostTracker
from search_router.config import SearchRouterConfig
from search_router.retry import RetryPolicy
from search_router.router import SearchRouter, RouteResult


# ── 辅助函数 ────────────────────────────────────────────

def _make_search_result(
    title: str = "test",
    url: str = "https://example.com/test",
    confidence_score: float = 0.5,
    freshness_score: float = 0.5,
    relevance_score: float = 0.5,
    source_credibility_score: float = 0.5,
    **kwargs,
) -> SearchResult:
    """构造 SearchResult，默认所有分数为合法值。"""
    return SearchResult(
        title=title,
        url=url,
        confidence_score=confidence_score,
        freshness_score=freshness_score,
        relevance_score=relevance_score,
        source_credibility_score=source_credibility_score,
        **kwargs,
    )


def _make_nan_result(nan_field: str, title: str = "nan_test") -> SearchResult:
    """构造指定字段为 NaN 的 SearchResult，其余字段为合法值。"""
    kwargs = {
        "title": title,
        "url": f"https://example.com/{title}",
        "confidence_score": 0.5,
        "freshness_score": 0.5,
        "relevance_score": 0.5,
        "source_credibility_score": 0.5,
    }
    kwargs[nan_field] = float("nan")
    return SearchResult(**kwargs)


def _make_request(query: str = "test query") -> SearchRequest:
    """构造默认 SearchRequest。"""
    return SearchRequest(query=query, task_type=TaskType.FALLBACK_LIGHT_SEARCH)


class _FakeAdapter:
    """可控的 Fake Adapter，返回预设结果。"""

    def __init__(self, results: list[SearchResult], cost: float = 0.01):
        self._results = results
        self._cost = cost
        self._provider_name = "mock"

    @property
    def provider_name(self):
        return self._provider_name

    @property
    def provider_type(self):
        from search_router.models.search_response import ProviderType
        return ProviderType.MOCK

    def is_available(self):
        return True

    async def search(self, request):
        return SearchResponse(
            success=True,
            provider=self._provider_name,
            results=self._results,
            total_results=len(self._results),
            estimated_cost=self._cost,
        )

    def estimate_cost(self, request):
        return self._cost

    def validate_config(self):
        return True


def _build_router_with_fake_adapter(
    results: list[SearchResult],
    cost: float = 0.01,
    contract_validator: ContractValidator | None = None,
    quarantine_handler: QuarantineHandler | None = None,
    candidate_pool: CandidatePool | None = None,
    merger: ResultMerger | None = None,
) -> SearchRouter:
    """构造注入 FakeAdapter 的 SearchRouter。

    通过 patch MockProviderAdapter 使其返回预设结果。
    """
    fake = _FakeAdapter(results, cost)
    config = SearchRouterConfig(dry_run=True)
    cv = contract_validator or ContractValidator()
    qh = quarantine_handler or QuarantineHandler()
    pool = candidate_pool or CandidatePool()
    mrg = merger or ResultMerger()

    router = SearchRouter(
        config=config,
        contract_validator=cv,
        quarantine_handler=qh,
        candidate_pool=pool,
    )
    # 替换内部组件
    router._pool = pool
    router._merger = mrg
    return router, fake


async def _run_search_with_fake(results: list[SearchResult], **kwargs) -> RouteResult:
    """运行一次 search()，使用 FakeAdapter 注入预设结果。"""
    router, fake = _build_router_with_fake_adapter(results, **kwargs)
    request = _make_request()

    with patch.object(SearchRouter, "__init__", lambda self, **kw: None):
        # 手动设置 router 属性
        pass

    # 不用 patch，直接构造 router 并替换 adapter
    config = SearchRouterConfig(dry_run=True)
    cv = kwargs.get("contract_validator") or ContractValidator()
    qh = kwargs.get("quarantine_handler") or QuarantineHandler()
    pool = kwargs.get("candidate_pool") or CandidatePool()
    mrg = kwargs.get("merger") or ResultMerger()
    dedup = DedupManager()
    enhancer = GLMEnhancer(config)
    cost_tracker = CostTracker(config=config)
    retry = RetryPolicy()
    review_gate = DualReviewGate()

    router = SearchRouter(
        config=config,
        cost_tracker=cost_tracker,
        dedup_manager=dedup,
        enhancer=enhancer,
        candidate_pool=pool,
        review_gate=review_gate,
        retry_policy=retry,
        contract_validator=cv,
        quarantine_handler=qh,
    )
    router._merger = mrg

    # Patch RetryPolicy.execute 使其直接调用 adapter.search
    async def _fake_execute(coro_factory, sleep=None):
        return await coro_factory()

    router._retry.execute = _fake_execute

    # Patch MockProviderAdapter.search 使其返回预设结果
    original_search = fake.search

    with patch("search_router.router.MockProviderAdapter", return_value=fake):
        result = await router.search(request)

    return result


# ════════════════════════════════════════════════════════
# 测试用例
# ════════════════════════════════════════════════════════


class TestContractGate:
    """Contract Gate 专项测试。"""

    # ── 1. source_credibility NaN → quarantine ─────────
    @pytest.mark.asyncio
    async def test_source_credibility_nan_quarantined(self):
        result = await _run_search_with_fake([
            _make_nan_result("source_credibility_score", title="sc_nan"),
        ])
        assert result.quarantine_stats["total_quarantined"] == 1
        assert result.quarantine_stats["total_valid"] == 0
        assert len(result.cards) == 0

    # ── 2. freshness NaN → quarantine ─────────────────
    @pytest.mark.asyncio
    async def test_freshness_nan_quarantined(self):
        result = await _run_search_with_fake([
            _make_nan_result("freshness_score", title="fr_nan"),
        ])
        assert result.quarantine_stats["total_quarantined"] == 1
        assert result.quarantine_stats["total_valid"] == 0
        assert len(result.cards) == 0

    # ── 3. relevance NaN → quarantine ─────────────────
    @pytest.mark.asyncio
    async def test_relevance_nan_quarantined(self):
        result = await _run_search_with_fake([
            _make_nan_result("relevance_score", title="rel_nan"),
        ])
        assert result.quarantine_stats["total_quarantined"] == 1
        assert result.quarantine_stats["total_valid"] == 0
        assert len(result.cards) == 0

    # ── 4. confidence NaN → quarantine ────────────────
    @pytest.mark.asyncio
    async def test_confidence_nan_quarantined(self):
        result = await _run_search_with_fake([
            _make_nan_result("confidence_score", title="conf_nan"),
        ])
        assert result.quarantine_stats["total_quarantined"] == 1
        assert result.quarantine_stats["total_valid"] == 0
        assert len(result.cards) == 0

    # ── 5. 合法 0.0 通过 Validator，再被 0.30 规则丢弃 ──
    @pytest.mark.asyncio
    async def test_valid_zero_then_discarded_by_pool(self):
        """0.0 分数合法通过 Validator，但 confidence<0.30 被 CandidatePool 丢弃。"""
        pool = CandidatePool()
        result = await _run_search_with_fake(
            [_make_search_result(confidence_score=0.0, freshness_score=0.0,
                                  relevance_score=0.0, source_credibility_score=0.0,
                                  title="zero_scores")],
            candidate_pool=pool,
        )
        # 通过 Validator（0.0 不是 NaN）
        assert result.quarantine_stats["total_valid"] == 1
        assert result.quarantine_stats["total_quarantined"] == 0
        # 但被 CandidatePool 丢弃（confidence < 0.30）
        assert len(result.cards) == 1  # card 仍在 result.cards 中
        pool_decisions = result.pool_decisions
        assert any(d.get("pool_name") == "discarded" for d in pool_decisions)

    # ── 6. 正常非 NaN 结果保持原链 ───────────────────
    @pytest.mark.asyncio
    async def test_normal_results_pass_through(self):
        result = await _run_search_with_fake([
            _make_search_result(title="normal_1"),
            _make_search_result(title="normal_2"),
        ])
        assert result.quarantine_stats["total_quarantined"] == 0
        assert result.quarantine_stats["total_valid"] >= 1
        assert len(result.cards) >= 1
        assert result.success is True

    # ── 7. 混合批次：valid 继续、NaN 隔离 ─────────────
    @pytest.mark.asyncio
    async def test_mixed_batch_valid_continues_nan_quarantined(self):
        result = await _run_search_with_fake([
            _make_search_result(title="valid_result"),
            _make_nan_result("source_credibility_score", title="nan_result"),
        ])
        assert result.quarantine_stats["total_input"] == 2
        assert result.quarantine_stats["total_quarantined"] == 1
        assert result.quarantine_stats["total_valid"] == 1
        # valid result goes through
        assert len(result.cards) >= 1
        # NaN result not in cards
        card_titles = [c.title for c in result.cards]
        assert "nan_result" not in card_titles

    # ── 8. 全部隔离：成本仍记录 ────────────────────────
    @pytest.mark.asyncio
    async def test_all_quarantined_cost_still_recorded(self):
        result = await _run_search_with_fake([
            _make_nan_result("source_credibility_score", title="all_nan_1"),
            _make_nan_result("freshness_score", title="all_nan_2"),
        ], cost=0.05)
        assert result.quarantine_stats["total_quarantined"] == 2
        assert result.quarantine_stats["total_valid"] == 0
        assert result.success is True
        assert len(result.cards) == 0
        assert len(result.pool_decisions) == 0
        # 成本仍记录
        assert result.total_cost == 0.05

    # ── 9. 连续两次 search 统计不串批 ──────────────────
    @pytest.mark.asyncio
    async def test_two_searches_no_stats_cross_contamination(self):
        """两次 search 的 quarantine_stats 互相独立。"""
        r1 = await _run_search_with_fake([
            _make_nan_result("source_credibility_score", title="nan_1"),
        ])
        r2 = await _run_search_with_fake([
            _make_search_result(title="valid_2"),
        ])
        assert r1.quarantine_stats["total_quarantined"] == 1
        assert r2.quarantine_stats["total_quarantined"] == 0
        assert r2.quarantine_stats["total_valid"] >= 1

    # ── 10. quarantine 不进入 Merger ──────────────────
    @pytest.mark.asyncio
    async def test_quarantine_not_in_merger(self):
        """被隔离的结果不进入 Merger（通过 merger.merge 调用参数验证）。"""
        merger = ResultMerger()
        # 记录 merge 调用时的参数
        original_merge = merger.merge
        merge_calls = []

        def tracking_merge(results):
            merge_calls.append(list(results))
            return original_merge(results)

        merger.merge = tracking_merge

        result = await _run_search_with_fake(
            [
                _make_search_result(title="valid"),
                _make_nan_result("source_credibility_score", title="nan_item"),
            ],
            merger=merger,
        )
        # Merger 只收到 valid 结果
        assert len(merge_calls) == 1
        merged_input = merge_calls[0]
        merged_titles = [r.title for r in merged_input]
        assert "nan_item" not in merged_titles
        assert "valid" in merged_titles

    # ── 11. quarantine 不进入 CandidatePool ───────────
    @pytest.mark.asyncio
    async def test_quarantine_not_in_candidate_pool(self):
        """被隔离的结果不进入 CandidatePool。"""
        pool = CandidatePool()
        result = await _run_search_with_fake(
            [
                _make_search_result(title="valid"),
                _make_nan_result("source_credibility_score", title="nan_item"),
            ],
            candidate_pool=pool,
        )
        # 只有 valid 的 card 进入 pool
        pool_all = pool.pending_review + pool.observing + pool.discarded
        pool_titles = [c.title for c in pool_all]
        # valid card (title might be modified by mapper/enhancer, but nan_item should not be there)
        assert "nan_item" not in pool_titles

    # ── 12. RouteResult.to_dict() 包含本批统计 ──────────
    @pytest.mark.asyncio
    async def test_to_dict_contains_quarantine_stats(self):
        result = await _run_search_with_fake([
            _make_nan_result("source_credibility_score", title="sc_nan"),
        ])
        d = result.to_dict()
        assert "quarantine_stats" in d
        qs = d["quarantine_stats"]
        assert qs["total_input"] == 1
        assert qs["total_quarantined"] == 1
        assert qs["total_valid"] == 0
        assert "by_category" in qs

    # ── 13. Validator 异常整批 fail closed ─────────────
    @pytest.mark.asyncio
    async def test_validator_exception_fail_closed(self):
        """ContractValidator.validate_batch 抛异常 → 整批 fail closed。"""
        cv = ContractValidator()
        # Patch validate_batch to raise
        cv.validate_batch = MagicMock(side_effect=RuntimeError("validator crash"))
        pool = CandidatePool()

        result = await _run_search_with_fake(
            [_make_search_result(title="should_be_closed")],
            contract_validator=cv,
            candidate_pool=pool,
        )
        # fail closed: no cards
        assert len(result.cards) == 0
        assert result.metadata.get("contract_validation_error") is True
        # no cards entered candidate pool
        pool_all = pool.pending_review + pool.observing + pool.discarded
        assert len(pool_all) == 0

    # ── 14. Handler 异常整批 fail closed ───────────────
    @pytest.mark.asyncio
    async def test_handler_exception_fail_closed(self):
        """QuarantineHandler.add 抛异常 → 整批 fail closed。"""
        qh = QuarantineHandler()
        qh.add = MagicMock(side_effect=RuntimeError("handler crash"))
        pool = CandidatePool()

        result = await _run_search_with_fake(
            [
                _make_search_result(title="valid_one"),
                _make_nan_result("source_credibility_score", title="nan_one"),
            ],
            quarantine_handler=qh,
            candidate_pool=pool,
        )
        # fail closed: no cards at all
        assert len(result.cards) == 0
        assert result.metadata.get("quarantine_handling_error") is True
        pool_all = pool.pending_review + pool.observing + pool.discarded
        assert len(pool_all) == 0

    # ── 15. 错误 metadata 不含异常原文 ──────────────────
    @pytest.mark.asyncio
    async def test_error_metadata_no_exception_text(self):
        """fail closed 时 metadata 只含固定错误码，不含 str(exc)/URL/query。"""
        cv = ContractValidator()
        cv.validate_batch = MagicMock(side_effect=RuntimeError("sensitive_info_leak"))
        qh = QuarantineHandler()
        qh.add = MagicMock(side_effect=RuntimeError("another_leak"))

        # Validator 异常
        result_v = await _run_search_with_fake(
            [_make_search_result(title="t")],
            contract_validator=cv,
        )
        meta_str = str(result_v.metadata)
        assert "sensitive_info_leak" not in meta_str
        assert "contract_validation_error" in meta_str

        # Handler 异常
        result_h = await _run_search_with_fake(
            [
                _make_search_result(title="valid"),
                _make_nan_result("source_credibility_score", title="nan"),
            ],
            quarantine_handler=qh,
        )
        meta_str_h = str(result_h.metadata)
        assert "another_leak" not in meta_str_h
        assert "quarantine_handling_error" in meta_str_h

    # ── 16. dry_run Mock 结果同样必须经过 Validator ────
    @pytest.mark.asyncio
    async def test_dry_run_mock_results_through_validator(self):
        """dry_run=true 时 Mock 结果同样要经过 ContractValidator 闸门。"""
        config = SearchRouterConfig(dry_run=True)
        cv = ContractValidator()
        qh = QuarantineHandler()

        # 使用 MockProviderAdapter 的默认数据，正常流程
        router = SearchRouter(
            config=config,
            contract_validator=cv,
            quarantine_handler=qh,
        )

        request = SearchRequest(
            query="美业",
            task_type=TaskType.CHINESE_INDUSTRY_NEWS,
        )
        result = await router.search(request)

        # Mock 结果默认分数是 NaN（SearchResult 默认值为 NaN）
        # 因此如果 Mock 结果有 NaN 字段，应该被隔离
        # 但实际要看 Mock 返回的 SearchResult 的分数
        # 关键是 quarantine_stats 必须存在且有值
        assert "quarantine_stats" in result.to_dict()
        qs = result.quarantine_stats
        assert "total_input" in qs
        assert "total_valid" in qs
        assert "total_quarantined" in qs
        assert qs["total_input"] + qs["total_quarantined"] >= 0  # sanity check
        # 确保 validator 确实被调用了（通过 quarantine_stats 非空判断）
        assert qs["total_input"] > 0  # Mock 至少返回了结果


class TestContractGateAdditional:
    """额外验证：NaN 绝不进入 CandidatePool。"""

    @pytest.mark.asyncio
    async def test_nan_never_enters_candidate_pool(self):
        """NaN 结果进入 CandidatePool 的比例必须为 0%。"""
        pool = CandidatePool()
        result = await _run_search_with_fake(
            [
                _make_nan_result("source_credibility_score", title="sc_nan"),
                _make_nan_result("freshness_score", title="fr_nan"),
                _make_nan_result("relevance_score", title="rel_nan"),
                _make_nan_result("confidence_score", title="conf_nan"),
                _make_search_result(title="valid_1", confidence_score=0.6),
            ],
            candidate_pool=pool,
        )
        pool_all = pool.pending_review + pool.observing + pool.discarded
        for card in pool_all:
            # NaN 检查: confidence_score 不应为 NaN
            assert not (isinstance(card.confidence_score, float) and math.isnan(card.confidence_score))

    @pytest.mark.asyncio
    async def test_quarantine_stats_by_category(self):
        """by_category 统计正确。"""
        result = await _run_search_with_fake([
            _make_nan_result("source_credibility_score", title="sc_nan_1"),
            _make_nan_result("source_credibility_score", title="sc_nan_2"),
            _make_nan_result("freshness_score", title="fr_nan"),
        ])
        by_cat = result.quarantine_stats["by_category"]
        assert by_cat.get("unrecognized_source") == 2
        assert by_cat.get("missing_publish_date") == 1

    @pytest.mark.asyncio
    async def test_full_quarantine_still_records_cost_and_success(self):
        """全部隔离：success=True, 成本仍记录, cards 为空。"""
        result = await _run_search_with_fake(
            [_make_nan_result("confidence_score", title="all_nan")],
            cost=0.03,
        )
        assert result.success is True
        assert result.total_cost == 0.03
        assert len(result.cards) == 0
        assert len(result.pool_decisions) == 0
        assert result.quarantine_stats["total_quarantined"] == 1

    @pytest.mark.asyncio
    async def test_handler_exception_no_results_in_pool(self):
        """Handler 异常时，即使有 valid 结果也不进 CandidatePool。"""
        qh = QuarantineHandler()
        qh.add = MagicMock(side_effect=RuntimeError("handler broke"))
        pool = CandidatePool()

        result = await _run_search_with_fake(
            [
                _make_search_result(title="valid_but_blocked"),
                _make_nan_result("freshness_score", title="nan_item"),
            ],
            quarantine_handler=qh,
            candidate_pool=pool,
        )
        # fail closed: 整批不进 pool
        pool_all = pool.pending_review + pool.observing + pool.discarded
        assert len(pool_all) == 0
        assert len(result.cards) == 0


# ── 同步运行辅助 ────────────────────────────────────────

def run_async(coro):
    """同步运行异步协程。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── 非异步 pytest 兼容层（如需同步调用）─────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
