"""测试 ProviderFactory mock/real 切换矩阵（T2B）。

不接真实 Key、不联网、不真实调用 Provider。
矩阵以「假 Key + enabled 开关」驱动，真实 Adapter 仅被实例化、从不发请求。
"""

import pytest

from search_router.config import SearchRouterConfig
from search_router.factory import ProviderFactory, is_real_adapter, PROVIDER_NAMES
from search_router.adapters.mock import MockProviderAdapter
from search_router.adapters.bocha import BochaAdapter
from search_router.adapters.glm_search import GLMSearchAdapter
from search_router.adapters.tavily import TavilyAdapter
from search_router.models.search_response import ProviderType


def _cfg(dry_run, bocha=False, glm=False, tavily=False, with_keys=True):
    return SearchRouterConfig(
        dry_run=dry_run,
        provider_bocha_enabled=bocha,
        provider_glm_search_enabled=glm,
        provider_tavily_enabled=tavily,
        bocha_api_key="bocha_test_key" if with_keys else "",
        zhipu_api_key="zhipu_test_key" if with_keys else "",
        tavily_api_key="tavily_test_key" if with_keys else "",
    )


def _real_map(providers):
    return {name: is_real_adapter(a) for name, a in providers.items()}


# ── 6 种切换矩阵 ───────────────────────────────────────

def test_matrix_row1_dry_run_all_mock():
    # dry_run=true，任意开关 → 全 Mock
    f = ProviderFactory(_cfg(True, bocha=True, glm=True, tavily=True))
    assert _real_map(f.create_providers()) == {"bocha": False, "glm_search": False, "tavily": False}


def test_matrix_row2_all_disabled_all_mock():
    # dry_run=false，三者全 false → 全 Mock
    f = ProviderFactory(_cfg(False, bocha=False, glm=False, tavily=False))
    assert _real_map(f.create_providers()) == {"bocha": False, "glm_search": False, "tavily": False}


def test_matrix_row3_only_bocha_real():
    f = ProviderFactory(_cfg(False, bocha=True))
    assert _real_map(f.create_providers()) == {"bocha": True, "glm_search": False, "tavily": False}


def test_matrix_row4_bocha_glm_real():
    f = ProviderFactory(_cfg(False, bocha=True, glm=True))
    assert _real_map(f.create_providers()) == {"bocha": True, "glm_search": True, "tavily": False}


def test_matrix_row5_all_real():
    f = ProviderFactory(_cfg(False, bocha=True, glm=True, tavily=True))
    assert _real_map(f.create_providers()) == {"bocha": True, "glm_search": True, "tavily": True}


def test_matrix_row6_only_glm_real():
    f = ProviderFactory(_cfg(False, glm=True))
    assert _real_map(f.create_providers()) == {"bocha": False, "glm_search": True, "tavily": False}


# ── dry_run 优先级最高 ─────────────────────────────────

def test_dry_run_overrides_even_with_keys_and_enabled():
    # dry_run=true 即使 enabled + key 存在，也全 Mock
    f = ProviderFactory(_cfg(True, bocha=True, glm=True, tavily=True, with_keys=True))
    assert all(not is_real_adapter(a) for a in f.create_providers().values())
    assert all(a.provider_type == ProviderType.MOCK for a in f.create_providers().values())


def test_should_use_real_false_when_dry_run():
    f = ProviderFactory(_cfg(True, bocha=True))
    assert f.should_use_real("bocha") is False


# ── 缺 Key 不触真实 ────────────────────────────────────

def test_enabled_but_no_key_falls_back_to_mock():
    # enabled 但无 key → 不得真实调用，降级 Mock
    f = ProviderFactory(_cfg(False, bocha=True, with_keys=False))
    assert is_real_adapter(f.create_providers()["bocha"]) is False


def test_key_present_but_not_enabled_stays_mock():
    # 有 key 但未 enabled → 不得因 key 存在就真实调用
    cfg = SearchRouterConfig(dry_run=False, provider_bocha_enabled=False, bocha_api_key="k123456")
    f = ProviderFactory(cfg)
    assert is_real_adapter(f.create_provider("bocha")) is False


# ── 真实 Adapter 类型正确 ──────────────────────────────

def test_real_adapter_classes():
    f = ProviderFactory(_cfg(False, bocha=True, glm=True, tavily=True))
    ps = f.create_providers()
    assert isinstance(ps["bocha"], BochaAdapter)
    assert isinstance(ps["glm_search"], GLMSearchAdapter)
    assert isinstance(ps["tavily"], TavilyAdapter)


def test_mock_substitute_keeps_provider_name():
    f = ProviderFactory(_cfg(False))  # 全 mock
    ps = f.create_providers()
    assert isinstance(ps["bocha"], MockProviderAdapter)
    assert ps["bocha"].provider_name == "bocha"  # 槽位名保留


def test_create_provider_unknown_raises():
    f = ProviderFactory(_cfg(True))
    with pytest.raises(ValueError):
        f.create_provider("unknown_provider")


def test_provider_names_constant():
    assert PROVIDER_NAMES == ("bocha", "glm_search", "tavily")
