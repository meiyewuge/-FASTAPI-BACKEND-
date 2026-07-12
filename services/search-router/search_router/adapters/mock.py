"""MockProviderAdapter — Mock 搜索 Provider。

不联网、不读 API Key、不调用任何外部服务。
返回固定构造的 mock 搜索结果。
cost=0，credits=0。

V1.1 修正：Mock 结果遵守正式 SearchResult 评分契约。
所有 score 字段为合法非 NaN 值，可通过 ContractValidator 闸门。
使用固定可解释的离线分数，trace 中标注 fixture_mode=mock_contract_valid。

兼容 V0.1.3 Mock 数据格式 + V1.1 Contract Gate 合规。
"""

from __future__ import annotations

import time

from search_router.adapters.base import BaseProviderAdapter
from search_router.models.search_request import SearchRequest, TaskType
from search_router.models.search_response import (
    SearchResponse,
    SearchResult,
    ProviderType,
)


# Mock 固定评分：满足正式评分契约，所有字段非 NaN
# source_credibility: 按 URL 域名查 _KNOWN_SOURCES 表，未命中给 0.55(C 级)
# freshness: 固定 0.70（模拟近 90 天发布）
# relevance: 固定 0.65（模拟中等相关）
# confidence = 0.45*src_cred + 0.25*freshness + 0.30*relevance
# final_score = confidence（与真实 Adapter 一致）
MOCK_DEFAULT_SCORES = {
    "source_credibility_score": 0.55,
    "freshness_score": 0.70,
    "relevance_score": 0.65,
}

# 按域名映射信源可信度（与 source_credibility_scorer _KNOWN_SOURCES 对齐）
MOCK_DOMAIN_CREDIBILITY = {
    "nmpa.gov.cn": 0.9,    # A 级
    "samr.gov.cn": 0.9,    # A 级
    "douyin.com": 0.4,     # D 级
    "meiye.cn": 0.55,      # C 级
    "beauty-industry.cn": 0.55,  # C 级
}


def _mock_credibility_for_url(url: str) -> float:
    """从 URL 域名查 Mock 信源可信度。未命中返回 0.55(C 级)。"""
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower().lstrip("www.")
        for domain, cred in MOCK_DOMAIN_CREDIBILITY.items():
            if hostname == domain or hostname.endswith("." + domain):
                return cred
    except Exception:
        pass
    return MOCK_DEFAULT_SCORES["source_credibility_score"]


def _mock_compute_scores(url: str) -> dict:
    """计算 Mock 固定评分，遵守正式契约。"""
    src_cred = _mock_credibility_for_url(url)
    fresh = MOCK_DEFAULT_SCORES["freshness_score"]
    rel = MOCK_DEFAULT_SCORES["relevance_score"]
    # confidence = 0.45*src_cred + 0.25*freshness + 0.30*relevance
    confidence = 0.45 * src_cred + 0.25 * fresh + 0.30 * rel
    confidence = max(0.0, min(1.0, confidence))
    trace = {
        "module": "mock_adapter",
        "fixture_mode": "mock_contract_valid",
        "weights": {"source_credibility": 0.45, "freshness": 0.25, "relevance": 0.30},
        "inputs": {
            "source_credibility_score": src_cred,
            "freshness_score": fresh,
            "relevance_score": rel,
        },
        "calculation": f"0.45*{src_cred:.3f} + 0.25*{fresh:.3f} + 0.30*{rel:.3f} = {confidence:.3f}",
        "reason": f"Mock固定评分(fixture_mode=mock_contract_valid): src_cred={src_cred:.3f}, freshness={fresh:.3f}, relevance={rel:.3f}",
    }
    return {
        "source_credibility_score": src_cred,
        "freshness_score": fresh,
        "relevance_score": rel,
        "confidence_score": confidence,
        "final_score": confidence,
        "computation_trace": trace,
    }


class MockProviderAdapter(BaseProviderAdapter):
    """Mock 搜索 Provider — 离线假数据。

    所有真实 Provider 在 dry_run 模式下均 fallback 到此 Mock。
    V1.1: Mock 结果遵守正式评分契约，可通过 ContractValidator。
    """

    # Mock 搜索结果池（按 task_type 分组，兼容 V0.1.3 格式）
    _MOCK_POOL: dict[str, list[dict]] = {
        TaskType.CHINESE_INDUSTRY_NEWS.value: [
            {
                "title": "美业数字化转型的五大趋势：AI 驱动门店经营升级",
                "url": "https://www.beauty-industry.cn/trends/ai-digital-2026",
                "summary": "2026年美业数字化转型加速，AI 视频生产、智能顾客管理、数据驱动经营成为核心趋势。",
                "source": "美业观察网",
                "publish_time": "2026-06-20T08:30:00",
                "evidence_excerpt": "调查显示，78%的美业门店计划在2026年引入AI工具",
            },
            {
                "title": "短视频营销成美业获客主渠道，抖音本地生活赋能门店",
                "url": "https://www.douyin.com/topic/beauty-marketing",
                "summary": "抖音本地生活为美业门店提供精准流量入口，短视频+直播成获客标配。",
                "source": "抖音商业观察",
                "publish_time": "2026-06-18T10:00:00",
                "evidence_excerpt": "美业门店抖音开户数同比增长210%",
            },
            {
                "title": "门店私域运营新范式：从会员卡到数据资产",
                "url": "https://www.meiye.cn/smart/private-domain",
                "summary": "美业门店私域运营从简单发券升级为数据驱动的全生命周期管理。",
                "source": "美业智慧",
                "publish_time": "2026-06-15T14:20:00",
                "evidence_excerpt": "私域复购率提升35%的门店共同特征：数据标签精细化",
            },
        ],
        TaskType.GLOBAL_AI_TOOLS.value: [
            {
                "title": "Runway Gen-3 Alpha: Next-Generation AI Video Generation",
                "url": "https://runwayml.com/blog/gen-3-alpha",
                "summary": "Runway releases Gen-3 Alpha with improved fidelity and temporal consistency for AI video generation.",
                "source": "Runway Blog",
                "publish_time": "2026-06-10T09:00:00",
                "evidence_excerpt": "Gen-3 Alpha produces 10-second high-fidelity video clips",
            },
            {
                "title": "Pika Labs 1.5: AI Video Creation for Everyone",
                "url": "https://pika.art/blog/pika-1-5",
                "summary": "Pika Labs launches 1.5 with new effects and improved motion control.",
                "source": "Pika Blog",
                "publish_time": "2026-06-08T12:00:00",
                "evidence_excerpt": "Pika 1.5 adds lip sync and motion brush features",
            },
            {
                "title": "Sora by OpenAI: Text-to-Video Model Technical Report",
                "url": "https://openai.com/blog/sora",
                "summary": "OpenAI introduces Sora, a text-to-video model capable of generating minute-long high-quality videos.",
                "source": "OpenAI Blog",
                "publish_time": "2026-06-05T15:00:00",
                "evidence_excerpt": "Sora generates videos up to 60 seconds with complex scene composition",
            },
        ],
        TaskType.OFFICIAL_DOCS.value: [
            {
                "title": "NMPA 关于化妆品功效宣称评价规范的公告",
                "url": "https://www.nmpa.gov.cn/xxgk/ggtk/hzhpb/202606.html",
                "summary": "国家药监局发布最新化妆品功效宣称评价规范，要求所有功效宣称必须有科学依据。",
                "source": "国家药品监督管理局",
                "publish_time": "2026-06-01T00:00:00",
                "evidence_excerpt": "化妆品注册人、备案人应当对功效宣称的科学性、真实性负责",
            },
            {
                "title": "广告法修订：医疗美容广告监管加强",
                "url": "https://www.samr.gov.cn/news/ad-law-2026",
                "summary": "市场监管总局修订广告法，加强医疗美容广告监管，禁止虚假功效宣称。",
                "source": "国家市场监督管理总局",
                "publish_time": "2026-05-28T00:00:00",
                "evidence_excerpt": "医疗美容广告必须取得医疗广告审查证明",
            },
        ],
        TaskType.TECHNICAL_RESEARCH.value: [
            {
                "title": "AI 视频生成技术在美业营销中的应用现状",
                "url": "https://research.beautytech.ai/ai-video-2026",
                "summary": "AI 视频生成技术在美业营销中的应用现状与趋势分析。",
                "source": "BeautyTech Research",
                "publish_time": "2026-06-12T00:00:00",
                "evidence_excerpt": "AI视频生成可将美业营销内容生产成本降低60%",
            },
            {
                "title": "医美抗衰技术进展：从外用到微创的范式转换",
                "url": "https://medical-aesthetics.org/anti-aging-2026",
                "summary": "医美抗衰技术从传统外用产品向微创/无创设备方向发展。",
                "source": "国际医学美容学会",
                "publish_time": "2026-06-08T00:00:00",
                "evidence_excerpt": "微创抗衰设备市场年增长率达25%",
            },
        ],
        TaskType.FALLBACK_LIGHT_SEARCH.value: [
            {
                "title": "美业行业快讯：本周热点摘要",
                "url": "https://news.beauty-industry.cn/weekly",
                "summary": "美业行业本周热点：AI工具、门店运营、合规政策等。",
                "source": "美业快讯",
                "publish_time": "2026-06-21T00:00:00",
                "evidence_excerpt": "本周美业相关投融资事件3起",
            },
        ],
    }

    def __init__(self, provider_name: str = "mock") -> None:
        """初始化 Mock Provider。

        Args:
            provider_name: Provider 名称（默认 "mock"，
                           dry_run 时可传入 "bocha_mock" / "tavily_mock" 等）
        """
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        """Provider 名称。"""
        return self._provider_name

    @property
    def provider_type(self) -> ProviderType:
        """Provider 类型：Mock。"""
        return ProviderType.MOCK

    def is_available(self) -> bool:
        """Mock Provider 始终可用。"""
        return True

    async def search(self, request: SearchRequest) -> SearchResponse:
        """执行 Mock 搜索。

        返回固定构造的假数据，不联网。
        根据 task_type 选择对应的 mock 数据池。
        根据 query 关键词做简单过滤以模拟相关性。
        V1.1: Mock 结果遵守正式评分契约，所有 score 字段非 NaN。
        """
        start_time = time.monotonic()

        task_type_value = (
            request.task_type.value
            if hasattr(request.task_type, "value")
            else str(request.task_type)
        )

        # 获取对应 task_type 的 mock 数据
        pool = self._MOCK_POOL.get(task_type_value, self._MOCK_POOL[TaskType.FALLBACK_LIGHT_SEARCH.value])

        # 根据 query 关键词做简单过滤
        query_lower = (request.query or "").lower()
        results: list[SearchResult] = []

        for item in pool:
            # 简单模拟：query 关键词在 title 或 summary 中出现则优先返回
            if (
                not query_lower
                or query_lower in item["title"].lower()
                or query_lower in item["summary"].lower()
                or any(kw in item["title"] or kw in item["summary"] for kw in query_lower.split())
            ):
                scores = _mock_compute_scores(item["url"])
                results.append(SearchResult(
                    title=item["title"],
                    url=item["url"],
                    summary=item.get("summary", ""),
                    source=item.get("source", ""),
                    publish_time=item.get("publish_time"),
                    provider=self._provider_name,
                    evidence_excerpt=item.get("evidence_excerpt", ""),
                    source_credibility_score=scores["source_credibility_score"],
                    freshness_score=scores["freshness_score"],
                    relevance_score=scores["relevance_score"],
                    confidence_score=scores["confidence_score"],
                    final_score=scores["final_score"],
                    computation_trace=scores["computation_trace"],
                ))

        # 如果没匹配到，返回全部
        if not results:
            for item in pool:
                scores = _mock_compute_scores(item["url"])
                results.append(SearchResult(
                    title=item["title"],
                    url=item["url"],
                    summary=item.get("summary", ""),
                    source=item.get("source", ""),
                    publish_time=item.get("publish_time"),
                    provider=self._provider_name,
                    evidence_excerpt=item.get("evidence_excerpt", ""),
                    source_credibility_score=scores["source_credibility_score"],
                    freshness_score=scores["freshness_score"],
                    relevance_score=scores["relevance_score"],
                    confidence_score=scores["confidence_score"],
                    final_score=scores["final_score"],
                    computation_trace=scores["computation_trace"],
                ))

        # 截取 max_results
        results = results[:request.max_results]

        latency_ms = int((time.monotonic() - start_time) * 1000)

        return SearchResponse(
            success=True,
            provider=self._provider_name,
            provider_type=ProviderType.MOCK,
            results=results,
            total_results=len(results),
            latency_ms=latency_ms,
            credits_used=0,       # Mock 不消耗 credits
            estimated_cost=0.0,   # Mock 不产生成本
            error=None,
            error_code="none",
        )

    def estimate_cost(self, request: SearchRequest) -> float:
        """Mock 搜索成本为 0。"""
        return 0.0

    def validate_config(self) -> bool:
        """Mock 不需要配置，始终合法。"""
        return True
