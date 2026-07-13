"""测试 dry_run 强制 Mock 铁律（T2B）。

dry_run=true 优先级最高：即使 enabled + Key 存在，也必须全 Mock，
且 force_real 必被拒绝。不接真实 Key、不联网、不真实调用。
"""

import pytest

from search_router.config import SearchRouterConfig
from search_router.factory import ProviderFactory, is_real_adapter
from search_router.manager import ProviderManager
from search_router.adapters.mock import MockProviderAdapter
from search_router.models.search_response import ProviderType


def _full_keys_all_enabled(dry_run):
    return SearchRouterConfig(
        dry_run=dry_run,
        provider_bocha_enabled=True,
        provider_glm_search_enabled=True,
        provider_tavily_enabled=True,
        bocha_api_key="bocha_test_key",
        zhipu_api_key="zhipu_test_key",
        tavily_api_key="tavily_test_key",
    )


def test_dry_run_forces_all_mock_even_with_keys():
    f = ProviderFactory(_full_keys_all_enabled(dry_run=True))
    providers = f.create_providers()
    assert all(not is_real_adapter(a) for a in providers.values())
    assert all(a.provider_type == ProviderType.MOCK for a in providers.values())


def test_dry_run_false_all_enabled_keys_present_all_real():
    f = ProviderFactory(_full_keys_all_enabled(dry_run=False))
    providers = f.create_providers()
    assert all(is_real_adapter(a) for a in providers.values())


def test_dry_run_manager_all_mock():
    m = ProviderManager(_full_keys_all_enabled(dry_run=True))
    for name in ("bocha", "glm_search", "tavily"):
        assert isinstance(m.get_provider(name), MockProviderAdapter)


def test_dry_run_force_real_rejected_for_every_provider():
    m = ProviderManager(_full_keys_all_enabled(dry_run=True))
    for name in ("bocha", "glm_search", "tavily"):
        assert m.force_real(name) is False
        assert isinstance(m.get_provider(name), MockProviderAdapter)


def test_dry_run_key_present_never_triggers_real():
    # 关键安全：环境变量里有 Key，但 dry_run=true → 绝不真实调用
    cfg = SearchRouterConfig(
        dry_run=True,
        provider_bocha_enabled=True,
        bocha_api_key="bocha_test_key",
    )
    f = ProviderFactory(cfg)
    assert f.should_use_real("bocha") is False
    assert is_real_adapter(f.create_provider("bocha")) is False


def test_should_use_mock_helper_consistency_with_config():
    # config.should_use_mock() 与 factory 行为一致：dry_run=true → 走 Mock
    cfg = _full_keys_all_enabled(dry_run=True)
    assert cfg.should_use_mock() is True


def test_toggle_dry_run_flips_real_mock():
    # 同一组 enabled+key，仅切 dry_run，结果应在 Mock / Real 间翻转
    on = ProviderFactory(_full_keys_all_enabled(dry_run=True)).create_providers()
    off = ProviderFactory(_full_keys_all_enabled(dry_run=False)).create_providers()
    assert all(not is_real_adapter(a) for a in on.values())
    assert all(is_real_adapter(a) for a in off.values())
