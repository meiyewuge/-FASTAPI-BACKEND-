"""EnricherOrchestrator — B1 离线集成协调器。

资格过滤(7条件) + 原子变更(deepcopy+全成功才提交) + 重算5字段 + enrichment trace。
本轮只使用Fake实现，禁止创建RealFetcher/RealResolver/RealRobotsProvider。

V1.2修正（微任务C）：
- RobotsProviderProtocol统一为get_robots()（与enrich_publish_time实际调用一致）
- 补取成功后同步更新computation_trace顶层(freshness_score/confidence_score/final_score/_freshness/_confidence)
"""
from __future__ import annotations

import asyncio
import copy
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Protocol
from urllib.parse import urlparse

from search_router.config import SearchRouterConfig
from search_router.models.search_response import SearchResult
from search_router.enrichers.publish_time_enricher import (
    enrich_publish_time,
    _PUBLISHED_TIME_APPROVED_DOMAINS,
    _resolve_domain,
)
from search_router.scorers.freshness_scorer import score_freshness
from search_router.scorers.confidence_scorer import score_confidence
from search_router.enrichers.standard_robots_provider import StandardRobotsProvider, RobotsDecision


# ── 依赖注入 Protocol ──────────────────────────────────

class SafeFetcherProtocol(Protocol):
    """安全fetch协议：内部处理DNS+Ticket+连接+peer验证+重定向。"""
    async def fetch(
        self,
        url: str,
        approved_domains: set[str] | None = None,
    ) -> Any: ...


class RobotsProviderProtocol(Protocol):
    """V1.2: 统一为get_robots()，与enrich_publish_time实际调用一致。"""
    async def get_robots(self, scheme: str, hostname: str) -> tuple[int, str, str]: ...


# ── 批准域名 ────────────────────────────────────────────

APPROVED_DOMAINS = {"news.cn", "chinadaily.com.cn", "stcn.com"}



class EnricherOrchestrator:
    """Enricher协调器：资格过滤 → 逐条补取 → 原子变更提交。

    Args:
        safe_fetcher: 安全fetch协议（内部处理DNS+Ticket+连接+peer验证）
        robots_provider: robots决策协议（本轮Fake）
        approved_domains: 批准域名集合
        reference_time: 参考时间
    """

    def __init__(
        self,
        safe_fetcher: SafeFetcherProtocol,
        robots_provider: RobotsProviderProtocol,
        approved_domains: set[str] | None = None,
        reference_time: datetime | None = None,
    ) -> None:
        self._safe_fetcher = safe_fetcher
        self._robots_provider = robots_provider
        self._approved_domains = approved_domains if approved_domains is not None else APPROVED_DOMAINS
        self._reference_time = reference_time
        # G0: 存储StandardRobotsProvider引用以便后续使用check_robots()
        self._is_standard_robots = isinstance(robots_provider, StandardRobotsProvider)

    def _is_eligible(self, result: SearchResult) -> tuple[bool, str]:
        """检查单条结果是否满足7条资格条件。"""
        # 1. provider == "tavily"
        if result.provider != "tavily":
            return False, "not_tavily"
        # 2. publish_time 为 None、空字符串或纯空白
        pt = result.publish_time
        if pt is not None and str(pt).strip():
            return False, "publish_time_already_present"
        # 3. source_credibility_score 非 NaN
        if math.isnan(result.source_credibility_score):
            return False, "source_credibility_nan"
        # 4. tier 为 A(>=0.9) 或 B(>=0.8)
        src_cred = result.source_credibility_score
        if src_cred < 0.8:
            return False, f"tier_not_ab({src_cred:.2f})"
        # 5. URL 为 HTTP/HTTPS
        url = result.url or ""
        if not url.startswith(("http://", "https://")):
            return False, "not_http_https"
        # 6. 域名属于 approved_domains
        try:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            resolved = _resolve_domain(hostname)
            if not resolved or resolved not in self._approved_domains:
                return False, "domain_not_approved"
        except Exception:
            return False, "invalid_url"
        # 7. 批次尚未进入 Validator/Merger/CandidatePool
        #    (由调用方保证，此处仅检查trace中无下游标记)
        trace = result.computation_trace or {}
        if "_contract_validation" in trace or "_merger" in trace or "_pool" in trace:
            return False, "already_downstream"
        return True, ""

    async def enrich_batch(
        self,
        results: list[SearchResult],
        config: SearchRouterConfig,
    ) -> list[SearchResult]:
        """批量补取：逐条过滤 → 补取 → 原子变更提交。

        Args:
            results: 搜索结果列表
            config: 配置对象

        Returns:
            补取后的结果列表（未修改的保持原样）
        """
        max_batch = config.publish_time_enricher_max_batch
        max_concurrent = config.publish_time_enricher_max_concurrent
        max_per_domain = config.publish_time_enricher_max_per_domain

        # 资格过滤
        eligible: list[tuple[int, SearchResult]] = []
        for i, r in enumerate(results):
            ok, reason = self._is_eligible(r)
            if ok:
                eligible.append((i, r))

        # 限制批次大小
        eligible = eligible[:max_batch]

        if not eligible:
            return results

        # 域名并发计数
        domain_inflight: dict[str, int] = {}

        async def _enrich_one(idx: int, result: SearchResult, sem: asyncio.Semaphore) -> tuple[int, SearchResult]:
            async with sem:
                # 域名并发限制
                try:
                    parsed = urlparse(result.url)
                    domain = _resolve_domain((parsed.hostname or "").lower().rstrip(".")) or ""
                except Exception:
                    domain = ""
                while domain_inflight.get(domain, 0) >= max_per_domain:
                    await asyncio.sleep(0.01)
                domain_inflight[domain] = domain_inflight.get(domain, 0) + 1
                try:
                    return await self._enrich_single(idx, result)
                finally:
                    domain_inflight[domain] = domain_inflight.get(domain, 0) - 1

        sem = asyncio.Semaphore(max_concurrent)
        tasks = [_enrich_one(idx, r, sem) for idx, r in eligible]
        enriched_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并结果：替换成功enriched的条目
        output = list(results)  # shallow copy
        for item in enriched_results:
            if isinstance(item, Exception):
                # 单条异常不影响其他条目
                continue
            idx, enriched = item
            output[idx] = enriched

        return output

    async def _enrich_single(self, idx: int, result: SearchResult) -> tuple[int, SearchResult]:
        """单条补取：deepcopy → 补取 → 验证 → 提交/回滚。"""
        # 原子变更：先deepcopy
        candidate = copy.deepcopy(result)

        # 保存原始值
        orig_publish_time = candidate.publish_time
        orig_freshness = candidate.freshness_score
        orig_confidence = candidate.confidence_score
        orig_final = candidate.final_score
        orig_trace = copy.deepcopy(candidate.computation_trace)

        try:
            # G0: robots预检查（仅StandardRobotsProvider实例）
            if self._is_standard_robots:
                try:
                    parsed = urlparse(candidate.url)
                    scheme = parsed.scheme
                    hostname = (parsed.hostname or "").lower().rstrip(".")
                    path = parsed.path or "/"
                    robots_result = await self._robots_provider.check_robots(scheme, hostname, path)
                    if robots_result.decision == RobotsDecision.DENY:
                        candidate.computation_trace = copy.deepcopy(orig_trace)
                        candidate.computation_trace["_enrichment"] = {
                            "status": "skipped",
                            "reason_code": "robots_denied",
                            "evidence_level": "NONE",
                        }
                        return idx, candidate
                    if robots_result.decision == RobotsDecision.UNAVAILABLE:
                        candidate.computation_trace = copy.deepcopy(orig_trace)
                        candidate.computation_trace["_enrichment"] = {
                            "status": "skipped",
                            "reason_code": "robots_unavailable",
                            "evidence_level": "NONE",
                        }
                        return idx, candidate
                except Exception:
                    # robots预检查异常 → fail-closed, 标记unavailable
                    candidate.computation_trace = copy.deepcopy(orig_trace)
                    candidate.computation_trace["_enrichment"] = {
                        "status": "skipped",
                        "reason_code": "robots_unavailable",
                        "evidence_level": "NONE",
                    }
                    return idx, candidate

            # 调用 enrich_publish_time
            enr_result = await enrich_publish_time(
                result=candidate,
                safe_fetcher=self._safe_fetcher,
                robots_provider=self._robots_provider,
                approved_domains=self._approved_domains,
                reference_time=self._reference_time,
            )

            if not enr_result.enriched:
                # 补取未成功 → 返回原样副本（追加trace）
                candidate.computation_trace = copy.deepcopy(orig_trace)
                candidate.computation_trace["_enrichment"] = {
                    "status": "skipped",
                    "reason_code": enr_result.skipped_reason,
                    "evidence_level": "NONE",
                }
                return idx, candidate

            # 补取成功 → 检查证据等级
            evidence = enr_result.evidence_level
            if evidence not in ("P1", "P2"):
                # 证据不足 → 回滚
                candidate.computation_trace = copy.deepcopy(orig_trace)
                candidate.computation_trace["_enrichment"] = {
                    "status": "skipped",
                    "reason_code": f"evidence_{evidence}",
                    "evidence_level": evidence,
                }
                return idx, candidate

            # 更新 publish_time
            candidate.publish_time = enr_result.publish_time

            # 重算 freshness_score — 使用正式Scorer
            # score_freshness内部strip了pub_dt的tzinfo，因此reference_time也必须naive
            _ref_for_scorer = self._reference_time
            if _ref_for_scorer is not None and _ref_for_scorer.tzinfo is not None:
                _ref_for_scorer = _ref_for_scorer.replace(tzinfo=None)
            freshness, fresh_trace = score_freshness(
                publish_time=candidate.publish_time,
                knowledge_type="default",
                reference_time=_ref_for_scorer,
            )
            candidate.freshness_score = freshness

            # 重算 confidence_score — 使用正式Scorer
            confidence, conf_trace = score_confidence(
                source_credibility_score=candidate.source_credibility_score,
                freshness_score=candidate.freshness_score,
                relevance_score=candidate.relevance_score,
                provider=candidate.provider,
            )
            candidate.confidence_score = confidence

            # final_score == confidence_score
            candidate.final_score = candidate.confidence_score

            # 全成功验证
            if (
                math.isnan(candidate.freshness_score)
                or math.isnan(candidate.confidence_score)
                or math.isnan(candidate.final_score)
                or candidate.final_score != candidate.confidence_score
            ):
                # 重算失败 → 回滚到原始评分
                candidate.publish_time = orig_publish_time
                candidate.freshness_score = orig_freshness
                candidate.confidence_score = orig_confidence
                candidate.final_score = orig_final
                candidate.computation_trace = copy.deepcopy(orig_trace)
                candidate.computation_trace["_enrichment"] = {
                    "status": "failed",
                    "reason_code": "recalc_nan_or_mismatch",
                    "evidence_level": evidence,
                    "extraction_method": enr_result.extraction_method,
                }
                return idx, candidate

            # V1.2 微任务C: 同步更新computation_trace顶层
            candidate.computation_trace = copy.deepcopy(orig_trace)
            candidate.computation_trace["freshness_score"] = candidate.freshness_score
            candidate.computation_trace["confidence_score"] = candidate.confidence_score
            candidate.computation_trace["final_score"] = candidate.final_score
            candidate.computation_trace["_freshness"] = fresh_trace
            candidate.computation_trace["_confidence"] = conf_trace
            candidate.computation_trace["_enrichment"] = {
                "status": "enriched",
                "reason_code": "",
                "evidence_level": evidence,
                "extraction_method": enr_result.extraction_method,
                "domain": enr_result.trace.get("domain", ""),
                "publish_time_before": str(orig_publish_time) if orig_publish_time is not None else "None",
                "publish_time_after": str(candidate.publish_time),
                "freshness_before": f"{orig_freshness:.3f}" if not math.isnan(orig_freshness) else "NaN",
                "freshness_after": f"{candidate.freshness_score:.3f}",
                "confidence_before": f"{orig_confidence:.3f}" if not math.isnan(orig_confidence) else "NaN",
                "confidence_after": f"{candidate.confidence_score:.3f}",
            }

            return idx, candidate

        except Exception:
            # 单条异常 → 保持原样，追加失败trace
            candidate.publish_time = orig_publish_time
            candidate.freshness_score = orig_freshness
            candidate.confidence_score = orig_confidence
            candidate.final_score = orig_final
            candidate.computation_trace = copy.deepcopy(orig_trace)
            candidate.computation_trace["_enrichment"] = {
                "status": "failed",
                "reason_code": "single_item_exception",
                "evidence_level": "NONE",
            }
            return idx, candidate
