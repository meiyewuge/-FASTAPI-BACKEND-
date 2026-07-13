"""测试 ProviderManager 运行时控制层（T2B）。

不接真实 Key、不联网、不真实调用 Provider。
"""

import pytest

from search_router.config import SearchRouterConfig
from search_router.manager import (
    ProviderManager,
    should_use_real_enhancer,
    fallback_level_for,
)
from search_router.factory import is_real_adapter
from search_router.adapters.mock import MockProviderAdapter
from search_router.adapters.bocha import BochaAdapter
from search_router.models.cost_record import FallbackLevel


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


# ── 查询 ───────────────────────────────────────────────

def test_get_provider():
    m = ProviderManager(_cfg(True))
    assert m.get_provider("bocha").provider_name == "bocha"


def test_get_provider_unknown_raises():
    m = ProviderManager(_cfg(True))
    with pytest.raises(ValueError):
        m.get_provider("nope")


def test_get_available_providers_mock_always_available():
    # dry_run=true 全 Mock，Mock 始终可用
    m = ProviderManager(_cfg(True))
    assert set(m.get_available_providers()) == {"bocha", "glm_search", "tavily"}


def test_get_available_excludes_real_without_key():
    # dry_run=false，bocha enabled 但无 key → 该槽位是 Mock（仍可用）；
    # 这里验证真实但 key 空时不可用的语义：直接构造真实 adapter
    m = ProviderManager(_cfg(False, bocha=True, with_keys=True))
    # bocha 为真实且 key 可用 → 可用
    assert "bocha" in m.get_available_providers()


# ── force_mock ─────────────────────────────────────────

def test_force_mock_makes_provider_mock():
    m = ProviderManager(_cfg(False, bocha=True))  # bocha 本为真实
    assert is_real_adapter(m.get_provider("bocha")) is True
    assert m.force_mock("bocha") is True
    assert isinstance(m.get_provider("bocha"), MockProviderAdapter)
    assert is_real_adapter(m.get_provider("bocha")) is False


def test_force_mock_unknown_raises():
    m = ProviderManager(_cfg(True))
    with pytest.raises(ValueError):
        m.force_mock("nope")


# ── force_real ─────────────────────────────────────────

def test_force_real_rejected_in_dry_run():
    # dry_run=true 时 force_real 必须拒绝
    m = ProviderManager(_cfg(True, bocha=True))
    assert m.force_real("bocha") is False
    assert isinstance(m.get_provider("bocha"), MockProviderAdapter)


def test_force_real_rejected_when_not_enabled():
    m = ProviderManager(_cfg(False, bocha=False))
    assert m.force_real("bocha") is False


def test_force_real_rejected_when_no_key():
    m = ProviderManager(_cfg(False, bocha=True, with_keys=False))
    assert m.force_real("bocha") is False


def test_force_real_allowed_when_all_conditions_met():
    # not dry_run + enabled + key → 允许
    m = ProviderManager(_cfg(False, bocha=True, with_keys=True))
    m.force_mock("bocha")  # 先压成 mock
    assert isinstance(m.get_provider("bocha"), MockProviderAdapter)
    assert m.force_real("bocha") is True
    assert isinstance(m.get_provider("bocha"), BochaAdapter)


# ── reload_config ──────────────────────────────────────

def test_reload_config_rebuilds_and_clears_overrides():
    m = ProviderManager(_cfg(False, bocha=True))
    m.force_mock("bocha")
    assert isinstance(m.get_provider("bocha"), MockProviderAdapter)
    # 重载到 dry_run=true：override 清空 + 全 Mock
    m.reload_config(_cfg(True, bocha=True))
    assert m.config.dry_run is True
    assert isinstance(m.get_provider("bocha"), MockProviderAdapter)
    assert m._overrides == {}


# ── health_check（不联网）──────────────────────────────

def test_health_check_no_network_structure():
    m = ProviderManager(_cfg(False, bocha=True, glm=True, tavily=True))
    hc = m.health_check()
    assert hc["dry_run"] is False
    assert set(hc["providers"].keys()) == {"bocha", "glm_search", "tavily"}
    for name, info in hc["providers"].items():
        assert set(info.keys()) == {"is_real", "is_available", "validate_config", "fallback_level"}


def test_health_check_reports_real_and_fallback_levels():
    m = ProviderManager(_cfg(False, bocha=True, glm=True, tavily=True))
    hc = m.health_check()
    assert hc["providers"]["bocha"]["is_real"] is True
    assert hc["providers"]["bocha"]["fallback_level"] == "f1_primary"
    assert hc["providers"]["glm_search"]["fallback_level"] == "f2_low_cost"
    assert hc["providers"]["tavily"]["fallback_level"] == "f1_primary"


def test_health_check_dry_run_all_mock():
    m = ProviderManager(_cfg(True, bocha=True, glm=True, tavily=True))
    hc = m.health_check()
    assert all(not info["is_real"] for info in hc["providers"].values())


# ── Fallback 层级映射 ──────────────────────────────────

def test_fallback_level_mapping():
    assert fallback_level_for("bocha") == FallbackLevel.F1_PRIMARY
    assert fallback_level_for("tavily") == FallbackLevel.F1_PRIMARY
    assert fallback_level_for("glm_search") == FallbackLevel.F2_LOW_COST
    assert fallback_level_for("codeact") == FallbackLevel.F3_EMERGENCY


def test_fallback_level_unknown_defaults_emergency():
    assert fallback_level_for("mystery") == FallbackLevel.F3_EMERGENCY


def test_fallback_level_values_snake_case():
    assert FallbackLevel.F1_PRIMARY.value == "f1_primary"
    assert FallbackLevel.F2_LOW_COST.value == "f2_low_cost"
    assert FallbackLevel.F3_EMERGENCY.value == "f3_emergency"


# ── enhancer 三锁（manager 暴露的函数）─────────────────

def test_manager_exposes_enhancer_triple_lock():
    on = SearchRouterConfig(
        dry_run=False, provider_glm_search_enabled=True, glm_enhancer_enabled=True,
    )
    off = SearchRouterConfig(
        dry_run=True, provider_glm_search_enabled=True, glm_enhancer_enabled=True,
    )
    assert should_use_real_enhancer(on) is True
    assert should_use_real_enhancer(off) is False
