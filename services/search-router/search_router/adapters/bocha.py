"""BochaAdapter — 博查搜索 Provider Adapter 骨架（T2A）。

博查（Bocha AI）是中文国内资讯搜索主力源。

端点：
    Web Search: https://api.bochaai.com/v1/web-search
    AI Search:  https://api.bochaai.com/v1/ai-search
认证：
    Authorization: Bearer {api_key}
定价：
    Web Search ¥0.036/次
    AI Search  ¥0.060/次

路由：
    need_ai_summary=False → POST web-search
    need_ai_summary=True  → POST ai-search

⚠️ T2A 阶段：
    - 不接真实 Key、不联网、不调真实 Bocha API。
    - 所有 HTTP 请求由注入的 mock session 拦截（见 tests/test_bocha_adapter.py）。
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
    compute_relevance_from_bocha,
)


def _require_aiohttp():
    """惰性导入 aiohttp。

    仅在未注入 session（即真实 HTTP 调用）时才需要。
    T2A 测试通过注入 mock session 运行，不触发本函数，故不依赖 aiohttp。
    """
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


class BochaAdapter(BaseProviderAdapter):
    """博查搜索 Adapter 骨架。

    继承 BaseProviderAdapter，标准化输出统一 SearchResponse / SearchResult。
    """

    # ---- 端点常量 ----
    WEB_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/web-search"
    AI_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/ai-search"

    # ---- 定价（¥）----
    COST_WEB_SEARCH = 0.036
    COST_AI_SEARCH = 0.060

    # ---- 单次结果上限 ----
    MAX_RESULTS = 20

    # ---- 默认请求超时（秒）----
    DEFAULT_TIMEOUT = 15

    # freshness 映射：兼容短名（day/week/...）与 T1 TimeRange 值（oneDay/...）
    _FRESHNESS_MAP = {
        "day": "oneDay",
        "oneDay": "oneDay",
        "week": "oneWeek",
        "oneWeek": "oneWeek",
        "month": "oneMonth",
        "oneMonth": "oneMonth",
        "year": "oneYear",
        "oneYear": "oneYear",
    }

    def __init__(
        self,
        api_key: str = "",
        config: Any = None,
        session: Any = None,
    ) -> None:
        """初始化博查 Adapter。

        Args:
            api_key: 博查 API Key。为空时 is_available()/validate_config() 返回 False。
            config: 可选 SearchRouterConfig；api_key 为空时从 config.bocha_api_key 兜底。
            session: 可选 aiohttp.ClientSession（或兼容的 mock）。
                     注入后所有 HTTP 走该 session —— T2A 测试据此拦截，绝不联网。
        """
        self._config = config
        self._api_key = api_key or (getattr(config, "bocha_api_key", "") if config else "")
        self._session = session

    # ── 基本属性 ───────────────────────────────────────

    @property
    def provider_name(self) -> str:
        """Provider 名称。"""
        return "bocha"

    @property
    def provider_type(self) -> ProviderType:
        """Provider 类型：PRIMARY（中文资讯主力）。"""
        return ProviderType.PRIMARY

    def is_available(self) -> bool:
        """api_key 非空时可用。"""
        return bool(self._api_key and self._api_key.strip())

    def validate_config(self) -> bool:
        """校验配置：api_key 非空即合法。"""
        return bool(self._api_key and self._api_key.strip())

    def estimate_cost(self, request: SearchRequest) -> float:
        """预估单次成本（¥）。

        need_ai_summary=True → AI Search ¥0.060
        否则 → Web Search ¥0.036
        """
        return self.COST_AI_SEARCH if request.need_ai_summary else self.COST_WEB_SEARCH

    # ── 请求构造 ───────────────────────────────────────

    def _map_freshness(self, time_range: str | None) -> str:
        """time_range → 博查 freshness 参数。未指定/未知 → noLimit。"""
        if not time_range:
            return "noLimit"
        return self._FRESHNESS_MAP.get(time_range, "noLimit")

    def _build_headers(self) -> dict[str, str]:
        """构造请求头（Bearer 认证）。"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _endpoint_for(self, request: SearchRequest) -> str:
        """根据 need_ai_summary 选择端点。"""
        return self.AI_SEARCH_ENDPOINT if request.need_ai_summary else self.WEB_SEARCH_ENDPOINT

    def _build_payload(self, request: SearchRequest) -> dict[str, Any]:
        """构造请求体。

        基础体：{"query", "count", "freshness"}
        AI Search 追加 answer=True / stream=False；Web Search 追加 summary=True。
        """
        count = min(request.max_results, self.MAX_RESULTS)
        payload: dict[str, Any] = {
            "query": request.query,
            "count": count,
            "freshness": self._map_freshness(request.time_range),
        }
        if request.need_ai_summary:
            payload["answer"] = True
            payload["stream"] = False
        else:
            payload["summary"] = True
        return payload

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

    def _extract_items(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        """从博查响应中提取 webPages.value 列表。

        Web Search / AI Search 均以 data.webPages.value 承载来源条目。
        兼容顶层 webPages 的情形。
        """
        data = raw.get("data") or raw
        web_pages = data.get("webPages") if isinstance(data, dict) else None
        if isinstance(web_pages, dict):
            value = web_pages.get("value")
            if isinstance(value, list):
                return value
        return []

    def _normalize_results(self, raw: dict[str, Any]) -> list[SearchResult]:
        """raw 博查响应 → 统一 SearchResult 列表（截断至 MAX_RESULTS）。

        Phase1: 补齐5项评分 (source_credibility, freshness, relevance,
        confidence, computation_trace)。
        """
        items = self._extract_items(raw)
        results: list[SearchResult] = []
        for item in items[: self.MAX_RESULTS]:
            snippet = item.get("snippet", "") or ""
            long_summary = item.get("summary", "") or ""
            source_name = item.get("siteName", "") or ""
            publish_time = item.get("datePublished")

            # Phase1 评分链
            src_cred, src_trace = score_source_credibility(source_name, source_url=item.get("url", ""))
            fresh, fresh_trace = score_freshness(publish_time)
            rel, rel_trace = compute_relevance_from_bocha(len(snippet), bool(item.get("url")))
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
                    title=item.get("name", "") or item.get("title", ""),
                    url=item.get("url", ""),
                    summary=long_summary or snippet,
                    source=source_name,
                    publish_time=publish_time,
                    provider=self.provider_name,
                    evidence_excerpt=snippet,
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

    # ── 主入口 ─────────────────────────────────────────

    async def search(self, request: SearchRequest) -> SearchResponse:
        """执行博查搜索。

        - api_key 为空 → 返回 auth_fail 失败响应，不发请求。
        - need_ai_summary 决定走 ai-search / web-search。
        - 非 200 → 映射 ErrorCode 返回失败响应。
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
                error="Bocha API Key 未配置",
                error_code=ErrorCode.AUTH_FAIL.value,
            )

        url = self._endpoint_for(request)
        headers = self._build_headers()
        payload = self._build_payload(request)

        status, data = await self._post(url, payload, headers)
        latency_ms = int((time.monotonic() - start) * 1000)

        if status != 200:
            return SearchResponse(
                success=False,
                provider=self.provider_name,
                provider_type=self.provider_type,
                results=[],
                total_results=0,
                latency_ms=latency_ms,
                credits_used=0,
                estimated_cost=0.0,
                error=f"Bocha HTTP {status}",
                error_code=_status_to_error_code(status),
            )

        results = self._normalize_results(data)
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
