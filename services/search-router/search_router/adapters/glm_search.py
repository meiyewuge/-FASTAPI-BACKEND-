"""GLMSearchAdapter — 智谱 GLM 搜索 Provider Adapter。

智谱 GLM 搜索（search_pro）为免费源（GLM-4-flash 永久免费）。

端点：
    搜索：https://open.bigmodel.cn/api/paas/v4/web_search
    增强：https://open.bigmodel.cn/api/paas/v4/chat/completions
认证：
    Authorization: Bearer {api_key}
模型：
    glm-4-flash
机制：
    搜索：使用独立 Web Search API（/web_search），返回 search_result 数组
    增强：通过 _chat_completion() 纯文本 LLM 增强（不含 tools.web_search）
定价：
    0.0（免费）

Phase 2 GLM Real Bridge Patch:
    _chat_completion() 从 NotImplementedError 改为真实 bridge。
    使用 _post() + _build_chat_payload() 调用 Chat Completions endpoint。
    不含 tools.web_search，不触发联网检索。
    测试通过 mock _post() 验证，不接真实 Key，不联网。

Phase 2 GLM Web Search API Patch:
    search() 从 Chat Completions + tools.web_search 改为独立 Web Search API。
    使用 _build_web_search_payload() + _normalize_web_search_results()。
    _chat_completion() 保持不变，仍走 Chat Completions endpoint。
    link/media 为空时保留结果，不丢弃。
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
from search_router.scorers.confidence_scorer import score_confidence


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


class GLMSearchAdapter(BaseProviderAdapter):
    """智谱 GLM 搜索 Adapter 骨架。

    继承 BaseProviderAdapter，标准化输出统一 SearchResponse / SearchResult。
    """

    # ---- 端点常量 ----
    CHAT_COMPLETIONS_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    WEB_SEARCH_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/web_search"

    # ---- 模型 / 搜索引擎 ----
    DEFAULT_MODEL = "glm-4-flash"
    SEARCH_ENGINE = "search_pro"

    # ---- 定价（¥）：免费 ----
    COST_FREE = 0.0

    # ---- 单次结果上限 ----
    MAX_RESULTS = 20

    # ---- 默认请求超时（秒）----
    DEFAULT_TIMEOUT = 30

    # search_recency_filter 映射：兼容短名与 T1 TimeRange 值；默认 oneWeek
    _RECENCY_MAP = {
        "day": "oneDay",
        "oneDay": "oneDay",
        "week": "oneWeek",
        "oneWeek": "oneWeek",
        "month": "oneMonth",
        "oneMonth": "oneMonth",
        "year": "oneYear",
        "oneYear": "oneYear",
    }
    DEFAULT_RECENCY = "oneWeek"

    def __init__(
        self,
        api_key: str = "",
        config: Any = None,
        session: Any = None,
    ) -> None:
        """初始化 GLM 搜索 Adapter。

        Args:
            api_key: 智谱 API Key。为空时 is_available()/validate_config() 返回 False。
            config: 可选 SearchRouterConfig；api_key 为空时从 config.zhipu_api_key 兜底。
            session: 可选 aiohttp.ClientSession（或兼容的 mock）。
                     注入后所有 HTTP 走该 session —— T2A 测试据此拦截，绝不联网。
        """
        self._config = config
        self._api_key = api_key or (getattr(config, "zhipu_api_key", "") if config else "")
        self._session = session

    # ── 基本属性 ───────────────────────────────────────

    @property
    def provider_name(self) -> str:
        """Provider 名称。"""
        return "glm_search"

    @property
    def provider_type(self) -> ProviderType:
        """Provider 类型：FALLBACK（P0 通用 F2 备搜 / 免费 fallback 源）。

        说明：GLM 在 P0 中是通用备搜免费源，非 Bocha/Tavily 那类 F1 主搜 Provider。
        fallback_light_search 场景可优先使用 GLM，但其 Provider 类型仍为 fallback。
        """
        return ProviderType.FALLBACK

    def is_available(self) -> bool:
        """api_key 非空时可用。"""
        return bool(self._api_key and self._api_key.strip())

    def validate_config(self) -> bool:
        """校验配置：api_key 非空即合法。"""
        return bool(self._api_key and self._api_key.strip())

    def estimate_cost(self, request: SearchRequest) -> float:
        """预估单次成本（¥）：GLM-4-flash 免费，恒为 0.0。"""
        return self.COST_FREE

    # ── 请求构造 ───────────────────────────────────────

    def _map_recency(self, time_range: str | None) -> str:
        """time_range → search_recency_filter。未指定/未知 → 默认 oneWeek。"""
        if not time_range:
            return self.DEFAULT_RECENCY
        return self._RECENCY_MAP.get(time_range, self.DEFAULT_RECENCY)

    def _build_headers(self) -> dict[str, str]:
        """构造请求头（Bearer 认证）。"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: SearchRequest) -> dict[str, Any]:
        """构造 chat/completions + web_search tool 请求体。

        使用 tools.web_search，search_engine=search_pro，
        search_recency_filter 由 time_range 映射。
        """
        count = min(request.max_results, self.MAX_RESULTS)
        return {
            "model": self.DEFAULT_MODEL,
            "messages": [
                {"role": "user", "content": request.query},
            ],
            "tools": [
                {
                    "type": "web_search",
                    "web_search": {
                        "enable": True,
                        "search_engine": self.SEARCH_ENGINE,
                        "search_result": True,
                        "search_recency_filter": self._map_recency(request.time_range),
                        "count": count,
                    },
                }
            ],
        }

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
        """从 GLM 响应中提取检索结果数组。

        兼容多种承载位置：
          1. 顶层 web_search（智谱标准返回）
          2. choices[].message.tool_calls[].search_result
          3. 顶层 search_result
        """
        # 1. 顶层 web_search
        web_search = raw.get("web_search")
        if isinstance(web_search, list):
            return web_search

        # 2. tool_calls 内 search_result
        choices = raw.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                message = (choice or {}).get("message") or {}
                for call in message.get("tool_calls") or []:
                    sr = (call or {}).get("search_result")
                    if isinstance(sr, list):
                        return sr

        # 3. 顶层 search_result
        sr = raw.get("search_result")
        if isinstance(sr, list):
            return sr

        return []

    def _normalize_results(self, raw: dict[str, Any]) -> list[SearchResult]:
        """raw GLM 响应 → 统一 SearchResult 列表（截断至 MAX_RESULTS）。"""
        items = self._extract_items(raw)
        results: list[SearchResult] = []
        for item in items[: self.MAX_RESULTS]:
            content = item.get("content", "") or ""
            results.append(
                SearchResult(
                    title=item.get("title", "") or "",
                    url=item.get("link", "") or item.get("url", ""),
                    summary=content,
                    source=item.get("media", "") or "",
                    publish_time=item.get("publish_date") or item.get("publish_time"),
                    provider=self.provider_name,
                    evidence_excerpt=content[:200],
                    raw=dict(item),
                )
            )
        return results

    # ── Web Search API 请求构造 ─────────────────────────

    def _build_web_search_payload(self, request: SearchRequest) -> dict[str, Any]:
        """构造 Web Search API 请求体（不含 messages / tools / web_search）。

        使用独立 /web_search endpoint，返回 search_result 数组。
        """
        count = min(request.max_results, self.MAX_RESULTS)
        return {
            "search_query": request.query,
            "count": count,
            "search_engine": self.SEARCH_ENGINE,
            "search_recency_filter": self._map_recency(request.time_range),
            "content_size": "medium",
        }

    # ── Web Search 结果标准化 ───────────────────────────

    def _normalize_web_search_results(self, raw: dict[str, Any]) -> list[SearchResult]:
        """Web Search API 响应 → 统一 SearchResult 列表。

        读取 data["search_result"] 数组，每个 item 映射为 SearchResult。
        link/media 为空时自动生成兜底 URL（glm-search://ref_N），不丢弃结果。
        """
        items = raw.get("search_result")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        for idx, item in enumerate(items[: self.MAX_RESULTS]):
            if not isinstance(item, dict):
                continue

            title = item.get("title", "") or ""
            content = item.get("content", "") or ""
            link = item.get("link", "") or ""
            media = item.get("media", "") or ""
            publish_date = item.get("publish_date") or item.get("publish_time")

            # URL 逻辑：优先真实 link → media → 兜底 glm-search://ref_N
            raw_item = dict(item)
            real_url = link or media or ""

            if real_url:
                url = real_url
                raw_item["_url_missing"] = False
            else:
                # link/media 均为空 → 生成兜底 URL
                url = f"glm-search://ref_{idx + 1}"
                raw_item["_url_missing"] = True
                raw_item["_url_fallback"] = url

            # Phase1 评分链 (无硬编码0.75, 使用scorer计算)
            source_name = media or "glm_search"
            src_cred, src_trace = score_source_credibility(source_name, source_url=url)
            fresh, fresh_trace = score_freshness(publish_date)
            rel = 0.0  # GLM Web Search API 无 relevance score
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
                "_confidence": conf_trace,
            }

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    summary=content,
                    source=source_name,
                    publish_time=publish_date,
                    provider=self.provider_name,
                    evidence_excerpt=content[:200],
                    confidence_score=conf,
                    freshness_score=fresh,
                    relevance_score=rel,
                    source_credibility_score=src_cred,
                    final_score=conf,
                    computation_trace=comp_trace,
                    raw=raw_item,
                )
            )
        return results

    # ── 主入口 ─────────────────────────────────────────

    async def search(self, request: SearchRequest) -> SearchResponse:
        """执行 GLM 搜索（独立 Web Search API）。

        使用 /api/paas/v4/web_search endpoint，返回 search_result 数组。
        不使用 Chat Completions / tools.web_search。

        - api_key 为空 → 返回 auth_fail 失败响应，不发请求。
        - 非 200 → 映射 ErrorCode 返回失败响应。
        - 成功 → 标准化为统一 SearchResponse（cost 恒 0）。
        - link/media 为空 → 保留结果，不丢弃。
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
                error="GLM (智谱) API Key 未配置",
                error_code=ErrorCode.AUTH_FAIL.value,
            )

        headers = self._build_headers()
        payload = self._build_web_search_payload(request)

        status, data = await self._post(self.WEB_SEARCH_ENDPOINT, payload, headers)
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
                error=f"GLM Web Search HTTP {status}",
                error_code=_status_to_error_code(status),
            )

        results = self._normalize_web_search_results(data)
        return SearchResponse(
            success=True,
            provider=self.provider_name,
            provider_type=self.provider_type,
            results=results,
            total_results=len(results),
            latency_ms=latency_ms,
            credits_used=0,
            estimated_cost=self.COST_FREE,
            error=None,
            error_code=ErrorCode.NONE.value,
        )

    # ── Chat Completion Bridge（供 GLMEnhancer 调用）────────

    def _build_chat_payload(
        self,
        messages: list[dict[str, Any]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """构造纯 chat（不含 web_search tool）请求体。

        供 _chat_completion 复用。注意：不含 tools，故不会触发联网检索。
        """
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

    async def _chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """纯文本 chat completion，供 GLMEnhancer 调用。

        ⚠️ 不含 tools.web_search，不触发联网检索。
        仅做 LLM 结构化增强，返回 GLM Chat Completions JSON。

        调用链:
            GLMEnhancer._real_enhance()
              → adapter._chat_completion(messages)
                → adapter._post(CHAT_COMPLETIONS_ENDPOINT, payload, headers)
                  → session.post(...)  [测试中 mock，不联网]

        Args:
            messages: 消息列表（system + user）
            model: 模型名，默认 glm-4-flash
            temperature: 温度参数，默认 0.1

        Returns:
            GLM Chat Completions 响应 dict，格式:
            {
                "choices": [
                    {
                        "message": {
                            "content": "..."  # JSON 字符串
                        }
                    }
                ]
            }

        Raises:
            RuntimeError: api_key 为空
            ValueError: 响应结构异常（缺少 choices）
            其他异常由 _post 传播（网络错误等），由 GLMEnhancer 捕获降级
        """
        if not self.is_available():
            raise RuntimeError("GLM API Key 未配置，无法调用 _chat_completion")

        headers = self._build_headers()
        payload = self._build_chat_payload(messages, model=model, temperature=temperature)

        status, data = await self._post(
            self.CHAT_COMPLETIONS_ENDPOINT,
            payload,
            headers,
        )

        if status != 200:
            raise RuntimeError(f"GLM chat completion HTTP {status}: {data}")

        # 验证响应结构
        choices = data.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            raise ValueError(f"GLM 响应缺少 choices: {data}")

        return data
