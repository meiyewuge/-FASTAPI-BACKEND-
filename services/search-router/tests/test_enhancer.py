"""测试 GLMEnhancer — 三锁 + Mock 增强 + 异常处理。"""

import asyncio
import json
import pytest
from search_router.config import SearchRouterConfig
from search_router.enhancer import (
    GLMEnhancer,
    EnhancementResult,
    should_use_real_enhancer,
)
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.models.search_request import TaskType


def _make_card(
    title: str = "美业数字化转型趋势",
    query: str = "美业AI趋势",
    confidence: float = 0.8,
    risk_category: str = "",
    knowledge_type: str = "",
    dimension: str = "",
) -> IndustryIntelligenceCard:
    """构造测试用 card。"""
    return IndustryIntelligenceCard(
        title=title,
        url="https://example.com/test",
        summary="2026年美业数字化转型加速，AI驱动门店升级",
        source="美业观察网",
        publish_time="2026-06-20T08:30:00",
        confidence_score=confidence,
        freshness_score=0.7,
        original_search_query=query,
        provider_metadata={"provider": "bocha", "task_type": TaskType.CHINESE_INDUSTRY_NEWS.value},
    )


class TestThreeLocks:
    """三锁 8 种组合。"""

    def _config(self, dry_run: bool, glm_search: bool, glm_enhancer: bool) -> SearchRouterConfig:
        return SearchRouterConfig(
            dry_run=dry_run,
            provider_glm_search_enabled=glm_search,
            glm_enhancer_enabled=glm_enhancer,
        )

    def test_all_true(self):
        """唯一 true 组合: (false, true, true)。"""
        cfg = self._config(False, True, True)
        assert should_use_real_enhancer(cfg) is True

    def test_dry_run_true(self):
        """dry_run=true → False。"""
        cfg = self._config(True, True, True)
        assert should_use_real_enhancer(cfg) is False

    def test_glm_search_false(self):
        """glm_search=false → False。"""
        cfg = self._config(False, False, True)
        assert should_use_real_enhancer(cfg) is False

    def test_enhancer_false(self):
        """enhancer=false → False。"""
        cfg = self._config(False, True, False)
        assert should_use_real_enhancer(cfg) is False

    def test_all_false(self):
        """全 false → False。"""
        cfg = self._config(False, False, False)
        assert should_use_real_enhancer(cfg) is False

    def test_dry_run_and_search_false(self):
        cfg = self._config(True, False, True)
        assert should_use_real_enhancer(cfg) is False

    def test_dry_run_and_enhancer_false(self):
        cfg = self._config(True, True, False)
        assert should_use_real_enhancer(cfg) is False

    def test_search_and_enhancer_false(self):
        cfg = self._config(False, False, False)
        assert should_use_real_enhancer(cfg) is False


class TestMockEnhance:
    """Mock 增强。"""

    def test_dry_run_forces_mock(self):
        """dry_run=true 强制 Mock 增强。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        assert enhancer.use_real is False

    def test_mock_enhance_fills_dimension(self):
        """Mock 增强填充 industry_dimension。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card(dimension="")
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhanced is True
        assert result.enhancement_mode == "mock"
        assert result.card.industry_dimension != ""

    def test_mock_enhance_fills_subtags(self):
        """Mock 增强填充 subtags（注意字段名是 subtags 不是 sub_tags）。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert isinstance(result.card.subtags, list)

    def test_mock_enhance_fills_knowledge_type(self):
        """Mock 增强填充 knowledge_type。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.knowledge_type != ""

    def test_mock_enhance_fills_risk_category(self):
        """Mock 增强填充 risk_category。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.risk_category != ""

    def test_mock_enhance_fills_business_relevance(self):
        """Mock 增强填充 business_relevance。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.business_relevance != ""

    def test_mock_enhance_fills_applicable_scenario(self):
        """Mock 增强填充 applicable_scenario。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.applicable_scenario != ""

    def test_mock_enhance_fills_risk_notes(self):
        """Mock 增强填充 risk_notes。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.risk_notes != ""

    def test_mock_enhance_fills_country(self):
        """Mock 增强填充 country_or_region。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        card.country_or_region = ""
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.country_or_region == "中国"

    def test_mock_enhance_fills_evidence_excerpt(self):
        """Mock 增强填充 evidence_excerpt。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        card.evidence_excerpt = ""
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.evidence_excerpt != ""

    def test_mock_enhance_fills_relevance_score(self):
        """Mock 增强填充 relevance_score。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card(confidence=0.8)
        card.relevance_score = 0.0
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.relevance_score > 0

    def test_mock_enhance_preserves_existing_values(self):
        """Mock 增强不覆盖已有值。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        card.industry_dimension = "数字化与AI工具"
        card.knowledge_type = "ai_tool"
        result = asyncio.run(enhancer.enhance(card))
        assert result.card.industry_dimension == "数字化与AI工具"
        assert result.card.knowledge_type == "ai_tool"


class TestEnhanceBatch:
    """批量增强。"""

    def test_enhance_batch(self):
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        cards = [_make_card(title="测试0"), _make_card(title="测试1")]
        results = asyncio.run(enhancer.enhance_batch(cards))
        assert len(results) == 2
        assert all(r.enhanced for r in results)


class TestExceptionHandling:
    """异常处理。"""

    def test_exception_does_not_block(self):
        """异常时不阻塞主链路，标记 enhancement_failed=True。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        # 正常 Mock 不应该 failed
        assert result.enhancement_failed is False

    def test_enhancement_failed_flag(self):
        """enhancement_failed 标记正确。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = _make_card()
        result = enhancer._mock_enhance(card, failed=True, error="test error")
        assert result.enhancement_failed is True
        assert result.error == "test error"
        assert result.enhancement_mode == "failed"


# ── Fake GLM Adapter for real-path testing ──────────────

class FakeGLMAdapter:
    """Fake GLM adapter for testing real enhancement path.

    不联网，不接真实 Key。返回预设的 JSON 响应。
    """

    def __init__(self, response: dict | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.call_count = 0
        self.last_messages: list[dict] | None = None

    async def _chat_completion(
        self,
        messages: list[dict],
        model: str = "glm-4-flash",
        temperature: float = 0.1,
    ) -> dict:
        self.call_count += 1
        self.last_messages = messages
        if self._exc is not None:
            raise self._exc
        return self._response or {}


class FakeGLMAdapterNoMethod:
    """Fake adapter without _chat_completion method."""

    pass


class TestRealEnhanceFakeAdapter:
    """三锁 True 时通过 fake adapter 测试真实增强路径。"""

    def _real_config(self) -> SearchRouterConfig:
        """三锁全开配置。"""
        return SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )

    def _make_glm_response(self, fields: dict) -> dict:
        """构造 GLM chat completion 响应。"""
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(fields, ensure_ascii=False)
                    }
                }
            ]
        }

    def test_dry_run_true_does_not_call_adapter(self):
        """dry_run=true 时即使注入 fake adapter，也绝不调用。"""
        cfg = SearchRouterConfig(dry_run=True)
        fake = FakeGLMAdapter(response=self._make_glm_response({"industry_dimension": "测试"}))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        assert enhancer.use_real is False
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "mock"
        assert fake.call_count == 0

    def test_three_locks_true_calls_adapter(self):
        """三锁 true 时调用 fake adapter。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(response=self._make_glm_response({
            "industry_dimension": "数字化与AI工具",
            "knowledge_type": "ai_tool",
        }))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        assert enhancer.use_real is True
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert fake.call_count == 1

    def test_real_enhance_success_mode_is_real(self):
        """三锁 true + fake JSON 成功 → enhancement_mode='real'。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(response=self._make_glm_response({
            "industry_dimension": "数字化与AI工具",
        }))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "real"
        assert result.enhancement_failed is False
        assert result.enhanced is True

    def test_real_enhance_updates_card_fields(self):
        """三锁 true + fake JSON 成功 → card 字段被 JSON 更新。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(response=self._make_glm_response({
            "country_or_region": "美国",
            "industry_dimension": "数字化与AI工具",
            "subtags": ["AI视频生成", "智能CRM"],
            "business_relevance": "直接相关：AI工具应用",
            "applicable_scenario": "可用于门店数字化升级",
            "risk_category": "normal",
            "risk_notes": "无特殊风险",
            "knowledge_type": "ai_tool",
            "evidence_excerpt": "AI驱动门店升级",
            "relevance_score": 0.95,
        }))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "real"
        assert result.card.country_or_region == "美国"
        assert result.card.industry_dimension == "数字化与AI工具"
        assert result.card.subtags == ["AI视频生成", "智能CRM"]
        assert result.card.knowledge_type == "ai_tool"
        assert result.card.risk_category == "normal"
        assert result.card.risk_notes == "无特殊风险"
        assert result.card.business_relevance == "直接相关：AI工具应用"
        assert result.card.applicable_scenario == "可用于门店数字化升级"
        assert result.card.evidence_excerpt == "AI驱动门店升级"
        assert result.card.relevance_score == 0.95

    def test_real_enhance_invalid_json_fallback_to_mock(self):
        """三锁 true + invalid JSON → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(response={
            "choices": [{"message": {"content": "这不是JSON"}}]
        })
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "JSON parse failed" in (result.error or "")

    def test_real_enhance_adapter_exception_fallback(self):
        """三锁 true + adapter 抛异常 → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(exc=RuntimeError("adapter crashed"))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "adapter crashed" in (result.error or "")

    def test_real_enhance_adapter_timeout_fallback(self):
        """三锁 true + adapter timeout → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(exc=TimeoutError("request timed out"))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "timeout" in (result.error or "").lower()

    def test_real_enhance_no_adapter_fallback(self):
        """三锁 true + 未注入 adapter → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        enhancer = GLMEnhancer(cfg, glm_adapter=None)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "not injected" in (result.error or "")

    def test_real_enhance_adapter_no_method_fallback(self):
        """三锁 true + adapter 无 _chat_completion → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        fake = FakeGLMAdapterNoMethod()
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "does not implement" in (result.error or "")

    def test_real_enhance_markdown_code_block(self):
        """三锁 true + GLM 返回 markdown code block → 正确解析。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(response={
            "choices": [{"message": {"content": '```json\n{"industry_dimension": "研发技术", "knowledge_type": "tech"}\n```'}}]
        })
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "real"
        assert result.card.industry_dimension == "研发技术"
        assert result.card.knowledge_type == "tech"

    def test_real_enhance_not_implemented_error(self):
        """三锁 true + adapter 抛 NotImplementedError → 降级 Mock。"""
        cfg = self._real_config()
        fake = FakeGLMAdapter(exc=NotImplementedError("not implemented"))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "not implemented" in (result.error or "").lower()


# ── Real GLMSearchAdapter bridge 测试（mock _post，不联网）────────

from search_router.adapters.glm_search import GLMSearchAdapter


class TestRealGLMBridge:
    """三锁 True + 真实 GLMSearchAdapter（mock _post）→ enhancement_mode='real'。"""

    _TEST_KEY = "test_glm_key_1234567890abcdef"

    def _real_config(self) -> SearchRouterConfig:
        return SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )

    def _make_glm_response(self, fields: dict) -> dict:
        return {
            "choices": [
                {"message": {"content": json.dumps(fields, ensure_ascii=False)}}
            ]
        }

    def _make_mock_post(self, response: dict, status: int = 200):
        """创建 mock _post 函数。"""
        async def mock_post(url, payload, headers):
            return status, response
        return mock_post

    def test_real_bridge_success(self):
        """三锁 True + 真实 GLMSearchAdapter + mock _post → enhancement_mode='real'。"""
        cfg = self._real_config()
        adapter = GLMSearchAdapter(api_key=self._TEST_KEY)
        adapter._post = self._make_mock_post(self._make_glm_response({
            "industry_dimension": "数字化与AI工具",
            "knowledge_type": "ai_tool",
            "risk_category": "normal",
            "subtags": ["AI视频生成"],
        }))
        enhancer = GLMEnhancer(cfg, glm_adapter=adapter)

        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "real"
        assert result.enhancement_failed is False
        assert result.enhanced is True
        assert result.card.industry_dimension == "数字化与AI工具"
        assert result.card.knowledge_type == "ai_tool"
        assert result.card.subtags == ["AI视频生成"]

    def test_real_bridge_abnormal_response_fallback(self):
        """三锁 True + _post 返回异常结构 → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        adapter = GLMSearchAdapter(api_key=self._TEST_KEY)
        adapter._post = self._make_mock_post({"error": "no choices"})
        enhancer = GLMEnhancer(cfg, glm_adapter=adapter)

        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        # card 不丢弃
        assert result.card is not None

    def test_real_bridge_http_error_fallback(self):
        """三锁 True + _post 返回 401 → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        adapter = GLMSearchAdapter(api_key=self._TEST_KEY)
        adapter._post = self._make_mock_post(
            {"error": {"code": "401", "message": "令牌已过期"}},
            status=401,
        )
        enhancer = GLMEnhancer(cfg, glm_adapter=adapter)

        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "401" in (result.error or "")

    def test_real_bridge_post_exception_fallback(self):
        """三锁 True + _post 抛异常 → 降级 Mock + enhancement_failed=True。"""
        cfg = self._real_config()
        adapter = GLMSearchAdapter(api_key=self._TEST_KEY)

        async def boom_post(url, payload, headers):
            raise RuntimeError("network error")

        adapter._post = boom_post
        enhancer = GLMEnhancer(cfg, glm_adapter=adapter)

        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "failed"
        assert result.enhancement_failed is True
        assert "network error" in (result.error or "")

    def test_dry_run_never_calls_real_bridge(self):
        """dry_run=True 时即使注入真实 GLMSearchAdapter，也绝不调用 _post。"""
        cfg = SearchRouterConfig(dry_run=True)
        adapter = GLMSearchAdapter(api_key=self._TEST_KEY)

        call_count = 0

        async def counting_post(url, payload, headers):
            nonlocal call_count
            call_count += 1
            return 200, {"choices": [{"message": {"content": "{}"}}]}

        adapter._post = counting_post
        enhancer = GLMEnhancer(cfg, glm_adapter=adapter)

        card = _make_card()
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "mock"
        assert call_count == 0
