"""TavilyAdapter — Tavily 搜索 Provider Adapter 骨架（T2A）。

Tavily 为英文全球资讯搜索主力源，支持 Search + Extract 两类调用。

端点：
    Search:  https://api.tavily.com/search
    Extract: https://api.tavily.com/extract
认证：
    Authorization: Bearer {api_key}
定价：
    Basic    ¥0.056/次
    Advanced ¥0.112/次
    Extract  ¥0.056/URL（need_extract=True 时最多 5 个 URL）

路由：
    need_ai_summary=False → search_depth="basic"
    need_ai_summary=True  → search_depth="advanced"
    need_extract=True     → Search 后追加 Extract（最多 5 个 URL）

⚠️ T2A 阶段：
    - 不接真实 Key、不联网、不调真实 Tavily API。
    - 所有 HTTP 请求由注入的 mock session 拦截（见 tests/test_tavily_adapter.py）。
    - aiohttp 仅在真实调用路径惰性导入，模块顶层不含网络库。
"""

from __future__ import annotations

import time
from typing import Any

from search_router.adapters.base import BaseProviderAdapter
from search_router.models.search_request import SearchRequest
from search_router.models.search_response import (
    SearchResponse,
    SearchResult,
    ProviderType,
    ErrorCode,
)
from search_router.scorers.source_credibility_scorer import score_source_credibility
from search_router.scorers.freshness_scorer import score_freshness
from search_router.scorers.confidence_scorer import (
    score_confidence,
    compute_relevance_from_tavily_score,
)


def _require_aiohttp():
    """惰性导入 aiohttp（仅未注入 session 的真实调用路径需要）。"""
    try:
        import aiohttp  # noqa: WPS433 (lazy import by design)
    except ImportError as exc:  # pragma: no cover - 仅真实部署阶段触发
        raise RuntimeError(
            "aiohttp 未安装；真实 HTTP 调用需要 aiohttp。"
            "T2A 阶段通过注入 mock session 运行，无需 aiohttp。"
        ) from exc
    return aiohttp


def _status_to_error_code(status: int) -> str:
    """HTTP 状态码 → ErrorCode 值。"""
    if status in (401, 403):
        return ErrorCode.AUTH_FAIL.value
    if status == 429:
        return ErrorCode.RATE_LIMIT.value
    if 500 <= status < 600:
        return ErrorCode.SERVER_ERROR.value
    return ErrorCode.UNKNOWN.value


class TavilyAdapter(BaseProviderAdapter):
    """Tavily 搜索 Adapter 骨架。

    继承 BaseProviderAdapter，标准化输出统一 SearchResponse / SearchResult。
    """

    # ---- 端点常量 ----
    SEARCH_ENDPOINT = "https://api.tavily.com/search"
    EXTRACT_ENDPOINT = "https://api.tavily.com/extract"

    # ---- 定价（¥）----
    COST_BASIC = 0.056
    COST_ADVANCED = 0.112
    COST_EXTRACT_PER_URL = 0.056

    # ---- 上限 ----
    MAX_RESULTS = 10
    MAX_EXTRACT_URLS = 5

    # ---- 默认请求超时（秒）----
    DEFAULT_TIMEOUT = 20

    def __init__(
        self,
        api_key: str = "",
        config: Any = None,
        session: Any = None,
    ) -> None:
        """初始化 Tavily Adapter。

        Args:
            api_key: Tavily API Key。为空时 is_available()/validate_config() 返回 False。
            config: 可选 SearchRouterConfig；api_key 为空时从 config.tavily_api_key 兜底。
            session: 可选 aiohttp.ClientSession（或兼容的 mock）。
                     注入后所有 HTTP 走该 session —— T2A 测试据此拦截，绝不联网。
        """
        self._config = config
        self._api_key = api_key or (getattr(config, "tavily_api_key", "") if config else "")
        self._session = session

    # ── 基本属性 ───────────────────────────────────────

    @property
    def provider_name(self) -> str:
        """Provider 名称。"""
        return "tavily"

    @property
    def provider_type(self) -> ProviderType:
        """Provider 类型：PRIMARY（英文资讯主力）。"""
        return ProviderType.PRIMARY

    def is_available(self) -> bool:
        """api_key 非空时可用。"""
        return bool(self._api_key and self._api_key.strip())

    def validate_config(self) -> bool:
        """校验配置：api_key 非空即合法。"""
        return bool(self._api_key and self._api_key.strip())

    def estimate_cost(self, request: SearchRequest) -> float:
        """预估单次成本（¥）。

        base = advanced ¥0.112（need_ai_summary）否则 basic ¥0.056。
        need_extract=True 时叠加 Extract 费用：¥0.056 × min(max_results, 5)。
        Extract 数量按 max_results 估算，不依赖 include_domains 数量。

        示例：
            basic                       → ¥0.056
            advanced                    → ¥0.112
            basic + extract(5 URL)      → ¥0.056 + 5×¥0.056 = ¥0.336
            advanced + extract(5 URL)   → ¥0.112 + 5×¥0.056 = ¥0.392
        """
        base = self.COST_ADVANCED if request.need_ai_summary else self.COST_BASIC
        if request.need_extract:
            extract_count = min(request.max_results, self.MAX_EXTRACT_URLS)
            base += self.COST_EXTRACT_PER_URL * extract_count
        return round(base, 4)

    # ── 请求构造 ───────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        """构造请求头（Bearer 认证）。"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _search_depth(self, request: SearchRequest) -> str:
        """need_ai_summary → advanced，否则 basic。"""
        return "advanced" if request.need_ai_summary else "basic"

    def _build_payload(self, request: SearchRequest) -> dict[str, Any]:
        """构造 Search 请求体。

        include_domains / exclude_domains 直接透传；max_results 上限 10。
        """
        return {
            "query": request.query,
            "search_depth": self._search_depth(request),
            "max_results": min(request.max_results, self.MAX_RESULTS),
            "include_domains": list(request.include_domains),
            "exclude_domains": list(request.exclude_domains),
            "include_answer": request.need_ai_summary,
        }

    def _build_extract_payload(self, urls: list[str]) -> dict[str, Any]:
        """构造 Extract 请求体（最多 MAX_EXTRACT_URLS 个 URL）。"""
        return {"urls": urls[: self.MAX_EXTRACT_URLS]}

    # ── HTTP 边界（唯一触网处）───────────────────────────

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, dict[str, Any]]:
        """发起 POST 请求，返回 (status, json)。

        注入 session 时使用注入的；否则惰性创建 aiohttp.ClientSession。
        T2A 测试始终注入 mock session，本方法不触达真实网络。
        """
        session = self._session
        own_session = False
        if session is None:
            aiohttp = _require_aiohttp()
            session = aiohttp.ClientSession()
            own_session = True
        try:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.DEFAULT_TIMEOUT,
            ) as resp:
                status = getattr(resp, "status", 200)
                data = await resp.json()
                return status, (data or {})
        finally:
            if own_session:
                await session.close()

    # ── 结果标准化 ─────────────────────────────────────

    def _normalize_results(self, raw: dict[str, Any]) -> list[SearchResult]:
        """raw Tavily Search 响应 → 统一 SearchResult 列表（截断至 MAX_RESULTS）。

        Phase1: relevance经tanh规范化, 补齐5项评分+computation_trace。
        """
        items = raw.get("results")
        if not isinstance(items, list):
            return []
        results: list[SearchResult] = []
        for item in items[: self.MAX_RESULTS]:
            content = item.get("content", "") or ""
            raw_score = item.get("score", 0.0)
            try:
                raw_score = float(raw_score)
            except (TypeError, ValueError):
                raw_score = 0.0
            source_name = item.get("source", "") or ""
            publish_time = item.get("published_date") or item.get("publish_time")

            # Phase1 评分链 (Tavily: relevance必须经tanh规范化)
            src_cred, src_trace = score_source_credibility(source_name, source_url=item.get("url", ""))
            fresh, fresh_trace = score_freshness(publish_time)
            rel, rel_trace = compute_relevance_from_tavily_score(raw_score)
            conf, conf_trace = score_confidence(src_cred, fresh, rel, provider=self.provider_name)

            def _nf(v):
                import math
                return "NaN" if (isinstance(v, float) and math.isnan(v)) else v

            comp_trace = {
                "formula_version": "P0.2_Phase1_V1.2",
                "source_credibility_score": _nf(src_cred),
                "freshness_score": _nf(fresh),
                "relevance_score": _nf(rel),
                "weights": {"source_credibility": 0.45, "freshness": 0.25, "relevance": 0.30},
                "confidence_score": _nf(conf),
                "final_score": _nf(conf),
                "provider": self.provider_name,
                "quarantine_reason": "",
                "_source_credibility": src_trace,
                "_freshness": fresh_trace,
                "_relevance": rel_trace,
                "_confidence": conf_trace,
            }

            results.append(
                SearchResult(
                    title=item.get("title", "") or "",
                    url=item.get("url", ""),
                    summary=content,
                    source=source_name,
                    publish_time=publish_time,
                    provider=self.provider_name,
                    evidence_excerpt=content[:200],
                    confidence_score=conf,
                    freshness_score=fresh,
                    relevance_score=rel,
                    source_credibility_score=src_cred,
                    final_score=conf,
                    computation_trace=comp_trace,
                    raw=dict(item),
                )
            )
        return results

    def _merge_extract(
        self,
        results: list[SearchResult],
        extract_raw: dict[str, Any],
    ) -> None:
        """将 Extract 的正文按 URL 合并回对应 SearchResult.raw（原地修改）。"""
        extracted = extract_raw.get("results")
        if not isinstance(extracted, list):
            return
        by_url = {e.get("url"): e for e in extracted if isinstance(e, dict)}
        for r in results:
            hit = by_url.get(r.url)
            if hit:
                r.raw["extracted_content"] = hit.get("raw_content", "")

    # ── 主入口 ─────────────────────────────────────────

    async def search(self, request: SearchRequest) -> SearchResponse:
        """执行 Tavily 搜索（含可选 Extract）。

        - api_key 为空 → 返回 auth_fail 失败响应，不发请求。
        - need_ai_summary 决定 basic / advanced。
        - 非 200 → 映射 ErrorCode 返回失败响应。
        - need_extract=True 时对前 5 个结果 URL 追加 Extract 调用并合并正文。
        - 成功 → 标准化为统一 SearchResponse。
        """
        start = time.monotonic()

        if not self.is_available():
            return SearchResponse(
                success=False,
                provider=self.provider_name,
                provider_type=self.provider_type,
                results=[],
                total_results=0,
                latency_ms=0,
                credits_used=0,
                estimated_cost=0.0,
                error="Tavily API Key 未配置",
                error_code=ErrorCode.AUTH_FAIL.value,
            )

        headers = self._build_headers()
        payload = self._build_payload(request)

        status, data = await self._post(self.SEARCH_ENDPOINT, payload, headers)

        if status != 200:
            latency_ms = int((time.monotonic() - start) * 1000)
            return SearchResponse(
                success=False,
                provider=self.provider_name,
                provider_type=self.provider_type,
                results=[],
                total_results=0,
                latency_ms=latency_ms,
                credits_used=0,
                estimated_cost=0.0,
                error=f"Tavily HTTP {status}",
                error_code=_status_to_error_code(status),
            )

        results = self._normalize_results(data)

        # need_extract=True 时追加 Extract（最多 5 个 URL）
        if request.need_extract and results:
            urls = [r.url for r in results if r.url][: self.MAX_EXTRACT_URLS]
            if urls:
                ex_status, ex_data = await self._post(
                    self.EXTRACT_ENDPOINT,
                    self._build_extract_payload(urls),
                    headers,
                )
                if ex_status == 200:
                    self._merge_extract(results, ex_data)

        latency_ms = int((time.monotonic() - start) * 1000)
        return SearchResponse(
            success=True,
            provider=self.provider_name,
            provider_type=self.provider_type,
            results=results,
            total_results=len(results),
            latency_ms=latency_ms,
            credits_used=0,
            estimated_cost=self.estimate_cost(request),
            error=None,
            error_code=ErrorCode.NONE.value,
        )
