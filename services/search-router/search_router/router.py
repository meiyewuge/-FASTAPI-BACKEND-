"""SearchRouter — P0 主路由入口。

全链路：
1. 接收 SearchRequest
2. dry_run 判断 + 选择 provider_name
3. 创建 Provider Adapter
4. adapter.estimate_cost(request) — 成本预估（同步，不联网）
5. CostTracker.pre_check(provider, estimated_cost) — 成本前置拦截
6. 成本超限 → 返回 cost_exceeded（不调 adapter.search()）
7. Provider search（RetryPolicy 包裹）
7.5 ContractValidator.validate_batch() — NaN拦截闸门
   ├─ valid → Merger → Dedup → Mapper → Enhancer → CandidatePool → Review
   └─ quarantined → QuarantineHandler.add() → 禁止进入下游
8. ResultMerger.merge(results)
9. DedupManager.check_batch(...)
10. map_batch(results) → IndustryIntelligenceCard 列表
11. await GLMEnhancer.enhance(card)
12. CandidatePool.route_card(card)
13. DualReviewGate.check(card)
14. CostTracker.record_cost()
15. 返回结构化结果

Phase 2 Cost Guard Patch:
    成本预估前置到 adapter.search() 之前。
    adapter.estimate_cost(request) 是同步方法，不需要 await。
    超限时直接拦截，不产生真实 API 调用费用。

P0.2 Contract Gate Patch:
    在 adapter.search() 之后、Merger 之前插入 ContractValidator 闸门。
    NaN 结果被隔离到 QuarantineHandler，不进入 Merger/Dedup/Mapper/CandidatePool。
    异常时整批 fail closed，结果不进入 CandidatePool。

不接真实 Key、不联网、不部署、不替换线上 codeact_search_web。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from search_router.adapters.mock import MockProviderAdapter
from search_router.candidate_pool import CandidatePool, POOL_DISCARDED
from search_router.config import SearchRouterConfig
from search_router.contract_validator import ContractValidator
from search_router.cost_tracker import CostTracker
from search_router.dedup import DedupManager
from search_router.dual_review import DualReviewGate
from search_router.enhancer import GLMEnhancer
from search_router.factory import ProviderFactory
from search_router.merger import ResultMerger
from search_router.enrichers.orchestrator import EnricherOrchestrator
from search_router.mapper import map_batch
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import SearchResponse, SearchResult
from search_router.quarantine_handler import QuarantineHandler
from search_router.retry import RetryPolicy


# ── 路由场景策略 ────────────────────────────────────────

_SCENARIO_STRATEGY: dict[str, dict[str, Any]] = {
    TaskType.CHINESE_INDUSTRY_NEWS.value: {
        "primary": "bocha",
        "fallback": "glm_search",
        "emergency": "codeact",
    },
    TaskType.GLOBAL_AI_TOOLS.value: {
        "primary": "tavily",
        "fallback": "glm_search",
        "emergency": "codeact",
    },
    TaskType.OFFICIAL_DOCS.value: {
        "primary": "bocha",
        "fallback": "glm_search",
        "emergency": "codeact",
    },
    TaskType.TECHNICAL_RESEARCH.value: {
        "primary": "bocha",
        "fallback": "glm_search",
        "emergency": "codeact",
    },
    TaskType.FALLBACK_LIGHT_SEARCH.value: {
        "primary": "glm_search",
        "fallback": "",
        "emergency": "codeact",
    },
}


@dataclass
class RouteResult:
    """单次路由结果。"""
    request: SearchRequest
    success: bool = False
    cards: list[IndustryIntelligenceCard] = field(default_factory=list)
    pool_decisions: list[dict] = field(default_factory=list)
    review_decisions: list[dict] = field(default_factory=list)
    total_cost: float = 0.0
    provider_used: str = ""
    fallback_level: str = "F1"
    error: str | None = None
    error_code: str = "none"
    enhancement_modes: list[str] = field(default_factory=list)
    dedup_results: list[dict] = field(default_factory=list)
    merged_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    quarantine_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "request": self.request.to_dict(),
            "total_cards": len(self.cards),
            "cards": [c.to_dict() for c in self.cards],
            "pool_decisions": list(self.pool_decisions),
            "review_decisions": list(self.review_decisions),
            "total_cost": round(self.total_cost, 4),
            "provider_used": self.provider_used,
            "fallback_level": self.fallback_level,
            "error": self.error,
            "error_code": self.error_code,
            "enhancement_modes": list(self.enhancement_modes),
            "dedup_results": list(self.dedup_results),
            "merged_count": self.merged_count,
            "metadata": dict(self.metadata),
            "quarantine_stats": dict(self.quarantine_stats),
        }


class SearchRouter:
    """P0 主路由入口。

    dry_run=true 时全链路走 Mock，不联网、不接真实 Key。
    """

    def __init__(
        self,
        config: SearchRouterConfig | None = None,
        cost_tracker: CostTracker | None = None,
        dedup_manager: DedupManager | None = None,
        enhancer: GLMEnhancer | None = None,
        candidate_pool: CandidatePool | None = None,
        review_gate: DualReviewGate | None = None,
        retry_policy: RetryPolicy | None = None,
        glm_adapter: Any | None = None,
        contract_validator: ContractValidator | None = None,
        quarantine_handler: QuarantineHandler | None = None,
        enricher_orchestrator: EnricherOrchestrator | None = None,
    ) -> None:
        self._config = config or SearchRouterConfig()
        self._factory = ProviderFactory(self._config)
        self._cost_tracker = cost_tracker or CostTracker(config=self._config)
        self._dedup = dedup_manager or DedupManager()
        self._enhancer = enhancer or GLMEnhancer(self._config, glm_adapter=glm_adapter)
        self._pool = candidate_pool or CandidatePool()
        self._review_gate = review_gate or DualReviewGate()
        self._retry = retry_policy or RetryPolicy()
        self._merger = ResultMerger()
        self._contract_validator = contract_validator or ContractValidator()
        self._enricher_orchestrator = enricher_orchestrator
        self._quarantine_handler = quarantine_handler or QuarantineHandler()

    @property
    def config(self) -> SearchRouterConfig:
        return self._config

    async def search(self, request: SearchRequest) -> RouteResult:
        """执行完整搜索链路。

        Args:
            request: 搜索请求

        Returns:
            RouteResult: 结构化结果
        """
        result = RouteResult(request=request)
        task_type_str = (
            request.task_type.value
            if hasattr(request.task_type, "value")
            else str(request.task_type)
        )

        # 1. 获取场景策略
        strategy = _SCENARIO_STRATEGY.get(task_type_str, {})
        primary_provider = strategy.get("primary", "mock")
        fallback_provider = strategy.get("fallback", "")
        emergency_provider = strategy.get("emergency", "codeact")

        # 2. dry_run 强制 Mock
        if self._config.dry_run:
            provider_name = "mock"
            result.fallback_level = "F1"
        else:
            provider_name = primary_provider
            result.fallback_level = "F1"

        # 3. 创建 Provider（dry_run 时强制 Mock）
        #    先创建 adapter，才能调用 estimate_cost 做成本前置检查
        if self._config.dry_run:
            adapter = MockProviderAdapter()
        else:
            try:
                adapter = self._factory.create_provider(provider_name)
            except Exception:
                # Provider 创建失败 → 尝试 fallback
                if fallback_provider:
                    try:
                        adapter = self._factory.create_provider(fallback_provider)
                        result.fallback_level = "F2"
                        provider_name = fallback_provider
                    except Exception:
                        adapter = MockProviderAdapter()
                        result.fallback_level = "F3"
                        provider_name = "mock"
                else:
                    adapter = MockProviderAdapter()
                    result.fallback_level = "F3"
                    provider_name = "mock"

        result.provider_used = provider_name

        # 4. 成本前置检查（在 adapter.search() 之前）
        #    调用 adapter.estimate_cost(request) 获取真实预估成本
        #    estimate_cost 是同步方法，不需要 await
        #    如果 estimate_cost 抛异常，降级为 0.0，不阻塞搜索
        try:
            estimated_cost = adapter.estimate_cost(request)
        except Exception:
            estimated_cost = 0.0

        cost_check = self._cost_tracker.pre_check(
            provider=provider_name,
            estimated_cost=estimated_cost,
        )
        if not cost_check.allowed:
            result.error = f"Cost exceeded: {cost_check.reason}"
            result.error_code = "cost_exceeded"
            result.metadata["estimated_cost"] = round(estimated_cost, 4)
            return result

        # 5. 执行搜索（只有成本检查通过才调用 adapter.search()）
        try:
            search_response = await self._retry.execute(
                coro_factory=lambda: adapter.search(request),
            )
        except Exception as exc:
            # 全部失败 → F3 emergency 标记
            result.fallback_level = "F3"
            result.error = f"All providers failed: {exc}"
            result.error_code = "server_error"
            # F3 只标记，不真实调用 codeact
            result.metadata["f3_emergency"] = True
            result.metadata["f3_provider"] = emergency_provider
            return result

        if not search_response.success:
            result.error = search_response.error or "Search failed"
            result.error_code = search_response.error_code
            result.fallback_level = "F3"
            result.metadata["f3_emergency"] = True
            result.metadata["f3_provider"] = emergency_provider
            return result

        # ── Step 5.5: ContractValidator 闸门 ─────────────
        # NaN 拦截：adapter.search() 之后、Merger 之前
        raw_results = search_response.results
        quarantine_stats: dict = {
            "total_input": len(raw_results),
            "total_valid": 0,
            "total_quarantined": 0,
            "by_category": {},
        }
        valid_results: list[SearchResult] = []
        quarantined_results: list[tuple] = []
        _contract_gate_failed = False

        # ── Step 5.5: EnricherOrchestrator 补取（在Validator之前）──────────
        # 对 raw_results 做 publish_time 补取（仅 tavily + A/B tier + 无日期）
        # 关键：Enricher必须在Validator之前，否则缺日期的NaN结果会被隔离，
        # Enricher永远拿不到需要补日期的数据
        results_for_validation = raw_results
        if (
            self._config.publish_time_enricher_enabled
            and not self._config.dry_run
            and provider_name == "tavily"
            and self._enricher_orchestrator is not None
        ):
            try:
                results_for_validation = await self._enricher_orchestrator.enrich_batch(
                    raw_results, self._config
                )
            except Exception:
                # Enricher 整批异常 → fail closed，不回退到raw_results
                result.metadata["enricher_batch_error"] = True
                results_for_validation = []
        elif (
            self._config.publish_time_enricher_enabled
            and not self._config.dry_run
            and provider_name == "tavily"
            and self._enricher_orchestrator is None
        ):
            # 开关开启但Orchestrator未注入 → fail closed
            result.metadata["enricher_not_configured"] = True
            results_for_validation = []

        # ── Step 5.75: 强制ContractValidator ──────────
        try:
            validation_out = self._contract_validator.validate_batch(results_for_validation)
            valid_results = validation_out["valid"]
            quarantined_results = validation_out["quarantined"]
        except Exception:
            # Validator 异常 → 整批 fail closed
            _contract_gate_failed = True
            result.metadata["contract_validation_error"] = True
            quarantine_stats["total_quarantined"] = len(results_for_validation)

        if not _contract_gate_failed:
            try:
                by_category: dict[str, int] = {}
                for r, vr in quarantined_results:
                    self._quarantine_handler.add(r, vr)
                    # 局部计数分类（与 QuarantineHandler.add() 分类逻辑一致）
                    cat = "contract_error_quarantine"
                    reason = vr.quarantine_reason
                    if "信源未识别" in reason:
                        cat = "unrecognized_source"
                    elif "无发布日期" in reason:
                        cat = "missing_publish_date"
                    elif "置信度无法计算" in reason:
                        cat = "confidence_nan"
                    by_category[cat] = by_category.get(cat, 0) + 1

                quarantine_stats["total_valid"] = len(valid_results)
                quarantine_stats["total_quarantined"] = len(quarantined_results)
                quarantine_stats["by_category"] = by_category
            except Exception:
                # Handler 异常 → 整批 fail closed
                # V1.2: 统计必须反映实际终态，不能保留异常前的不完整计数
                _contract_gate_failed = True
                result.metadata["quarantine_handling_error"] = True
                quarantine_stats["total_valid"] = 0
                quarantine_stats["total_quarantined"] = quarantine_stats["total_input"]
                quarantine_stats["by_category"] = {"quarantine_handling_error": quarantine_stats["total_input"]}

        if _contract_gate_failed:
            # Fail closed: 不让任何结果进入下游
            valid_results = []

        result.quarantine_stats = quarantine_stats

        # 6. 跨 Provider 去重合并（只合并通过 Validator 的合法结果）
        merge_result = self._merger.merge(valid_results)
        merged_results = merge_result.results
        result.merged_count = merge_result.merged_count

        # 7. 跨任务历史去重
        urls = [r.url for r in merged_results if r.url]
        titles = [r.title for r in merged_results]
        dedup_results = self._dedup.check_batch(
            urls=urls,
            titles=titles,
            task_id=request.query[:50],
            provider=provider_name,
        )
        result.dedup_results = [d.to_dict() for d in dedup_results]

        # 8. SearchResult → IndustryIntelligenceCard 映射
        cards = map_batch(
            merged_results,
            task_type=task_type_str,
            query=request.query,
            estimated_cost=search_response.estimated_cost,
        )

        # 9. GLMEnhancer 增强
        for card in cards:
            enh_result = await self._enhancer.enhance(card)
            result.enhancement_modes.append(enh_result.enhancement_mode)

        # 10. CandidatePool 分流
        pool_decisions = self._pool.route_batch(cards)
        result.pool_decisions = [d.to_dict() for d in pool_decisions]

        # 11. DualReviewGate 审核
        review_decisions = self._review_gate.check_batch(cards)
        result.review_decisions = [d.to_dict() for d in review_decisions]

        # 12. 记录成本
        actual_cost = search_response.estimated_cost
        self._cost_tracker.record_cost(
            provider=provider_name,
            task_type=task_type_str,
            cost=actual_cost,
            success=True,
        )
        result.total_cost = actual_cost

        # 13. 返回结果
        result.success = True
        result.cards = cards
        result.metadata["dry_run"] = self._config.dry_run
        result.metadata["scenario"] = task_type_str
        result.metadata["strategy"] = strategy

        return result

    def search_sync(self, request: SearchRequest) -> RouteResult:
        """同步搜索（包装 async search）。"""
        return asyncio.run(self.search(request))
