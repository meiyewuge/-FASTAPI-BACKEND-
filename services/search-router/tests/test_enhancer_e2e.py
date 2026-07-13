"""E2E 测试 — GLMEnhancer 三锁端到端 + fake adapter real path。"""

import asyncio
import json
import pytest
from search_router.config import SearchRouterConfig
from search_router.enhancer import GLMEnhancer, should_use_real_enhancer
from search_router.models.intelligence_card import IndustryIntelligenceCard
from search_router.router import SearchRouter


class FakeGLMAdapter:
    """Fake GLM adapter for E2E testing."""

    def __init__(self, response: dict | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.call_count = 0

    async def _chat_completion(self, messages, model="glm-4-flash", temperature=0.1):
        self.call_count += 1
        if self._exc:
            raise self._exc
        return self._response or {}


def _make_glm_response(fields: dict) -> dict:
    return {
        "choices": [
            {"message": {"content": json.dumps(fields, ensure_ascii=False)}}
        ]
    }


class TestThreeLocksE2E:
    """三锁 8 组合端到端。"""

    @pytest.mark.parametrize("dry_run,glm_search,enhancer_enabled,expected", [
        (True, True, True, False),
        (True, True, False, False),
        (True, False, True, False),
        (True, False, False, False),
        (False, True, True, True),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, False),
    ])
    def test_eight_combinations(self, dry_run, glm_search, enhancer_enabled, expected):
        """8 种组合，唯一 (false,true,true) 为 True。"""
        cfg = SearchRouterConfig(
            dry_run=dry_run,
            provider_glm_search_enabled=glm_search,
            glm_enhancer_enabled=enhancer_enabled,
        )
        assert should_use_real_enhancer(cfg) is expected

    def test_dry_run_forces_mock_in_router(self):
        """dry_run=true 时 router 内 enhancer 强制 Mock。"""
        cfg = SearchRouterConfig(dry_run=True)
        fake = FakeGLMAdapter(response=_make_glm_response({"industry_dimension": "测试"}))
        router = SearchRouter(config=cfg, glm_adapter=fake)
        from search_router.models.search_request import SearchRequest, TaskType
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.success is True
        assert all(m == "mock" for m in result.enhancement_modes)
        assert fake.call_count == 0

    def test_three_locks_true_real_path_in_router(self):
        """三锁 true + fake adapter → router 走 real path。"""
        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )
        fake = FakeGLMAdapter(response=_make_glm_response({
            "industry_dimension": "数字化与AI工具",
            "knowledge_type": "ai_tool",
            "risk_category": "normal",
            "country_or_region": "中国",
        }))
        router = SearchRouter(config=cfg, glm_adapter=fake)
        from search_router.models.search_request import SearchRequest, TaskType
        req = SearchRequest(query="美业AI", task_type=TaskType.GLOBAL_AI_TOOLS)
        result = router.search_sync(req)
        assert result.success is True
        assert "real" in result.enhancement_modes
        assert fake.call_count > 0

    def test_three_locks_true_invalid_json_fallback(self):
        """三锁 true + invalid JSON → 降级 Mock。"""
        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )
        fake = FakeGLMAdapter(response={
            "choices": [{"message": {"content": "invalid JSON"}}]
        })
        router = SearchRouter(config=cfg, glm_adapter=fake)
        from search_router.models.search_request import SearchRequest, TaskType
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.success is True
        assert "failed" in result.enhancement_modes

    def test_three_locks_true_adapter_exception(self):
        """三锁 true + adapter 异常 → 降级 Mock。"""
        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )
        fake = FakeGLMAdapter(exc=RuntimeError("crashed"))
        router = SearchRouter(config=cfg, glm_adapter=fake)
        from search_router.models.search_request import SearchRequest, TaskType
        req = SearchRequest(query="美业", task_type=TaskType.CHINESE_INDUSTRY_NEWS)
        result = router.search_sync(req)
        assert result.success is True
        assert "failed" in result.enhancement_modes


class TestEnhancerCardFields:
    """增强后 card 字段验证。"""

    def test_real_enhance_updates_subtags(self):
        """三锁 true 时 real enhance 更新 subtags（不是 sub_tags）。"""
        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )
        fake = FakeGLMAdapter(response=_make_glm_response({
            "subtags": ["AI视频生成", "智能CRM"],
        }))
        enhancer = GLMEnhancer(cfg, glm_adapter=fake)
        card = IndustryIntelligenceCard(title="测试", url="https://example.com")
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhancement_mode == "real"
        assert result.card.subtags == ["AI视频生成", "智能CRM"]

    def test_mock_enhance_fills_fields(self):
        """Mock 增强填充产业字段。"""
        cfg = SearchRouterConfig(dry_run=True)
        enhancer = GLMEnhancer(cfg)
        card = IndustryIntelligenceCard(
            title="美业AI趋势",
            url="https://example.com",
            summary="AI驱动门店升级",
            original_search_query="美业AI",
        )
        result = asyncio.run(enhancer.enhance(card))
        assert result.enhanced is True
        assert result.card.industry_dimension  # 推断填充
        assert result.card.knowledge_type  # 推断填充
        assert result.card.risk_category  # 推断填充
