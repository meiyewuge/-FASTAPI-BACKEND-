"""ProviderManager — Provider 运行时控制层（T2B）。

职责：
    get_provider / get_available_providers
    force_mock / force_real
    reload_config
    health_check（不发真实网络请求）

附：
    should_use_real_enhancer(config) — GLM Enhancer 三锁判断
    FallbackLevel + fallback_level_for() — F1/F2/F3 fallback 骨架

⚠️ T2B 阶段：
    - 不联网、不真实调用 Provider。health_check 仅做配置 + Adapter 可用性检查。
    - force_real 仅在 not dry_run 且 enabled 且 key 可用时允许；dry_run=true 必拒绝。
    - codeact 仅作为 F3 emergency 标记，本阶段不真实调用、不替换线上 codeact_search_web。
"""

from __future__ import annotations

from search_router.config import SearchRouterConfig
from search_router.adapters.base import BaseProviderAdapter
from search_router.adapters.mock import MockProviderAdapter
from search_router.factory import ProviderFactory, PROVIDER_NAMES, is_real_adapter
from search_router.models.cost_record import FallbackLevel


# ── GLM Enhancer 三锁判断 ──────────────────────────────

def should_use_real_enhancer(config: SearchRouterConfig) -> bool:
    """三锁铁律：三者同时满足才允许真实 GLM 增强。

    1. SEARCH_ROUTER_DRY_RUN=false
    2. PROVIDER_GLM_SEARCH_ENABLED=true
    3. GLM_ENHANCER_ENABLED=true
    """
    return (
        not config.dry_run
        and config.provider_glm_search_enabled
        and config.glm_enhancer_enabled
    )


# ── Fallback 层级骨架（不做 T5 主路由）─────────────────

# Provider → fallback level 映射
_PROVIDER_FALLBACK_LEVEL = {
    "bocha": FallbackLevel.F1_PRIMARY,
    "tavily": FallbackLevel.F1_PRIMARY,
    "glm_search": FallbackLevel.F2_LOW_COST,
    "codeact": FallbackLevel.F3_EMERGENCY,  # 仅标记，不真实调用
}


def fallback_level_for(provider_name: str) -> FallbackLevel:
    """返回 Provider 的 fallback 层级。

    未知 Provider 默认归入 F3 emergency（最保守）。
    """
    return _PROVIDER_FALLBACK_LEVEL.get(provider_name, FallbackLevel.F3_EMERGENCY)


class ProviderManager:
    """Provider 运行时管理器。"""

    def __init__(self, config: SearchRouterConfig | None = None) -> None:
        self.config = config or SearchRouterConfig()
        self._factory = ProviderFactory(self.config)
        # 运行时强制覆盖：provider_name -> "mock" | "real"
        self._overrides: dict[str, str] = {}
        self._providers: dict[str, BaseProviderAdapter] = {}
        self._build()

    def _build(self) -> None:
        """按当前配置 + 覆盖重建 Provider 实例。"""
        self._providers = self._factory.create_providers()
        # 应用强制覆盖
        for name, mode in self._overrides.items():
            if mode == "mock":
                self._providers[name] = MockProviderAdapter(provider_name=name)
            elif mode == "real":
                self._providers[name] = self._factory._REAL_SPECS[name][0](
                    api_key=self._factory._key_for(name),
                    config=self.config,
                )

    # ── 查询 ──────────────────────────────────────────

    def get_provider(self, provider_name: str) -> BaseProviderAdapter:
        if provider_name not in self._providers:
            raise ValueError(f"未知 Provider: {provider_name}")
        return self._providers[provider_name]

    def get_available_providers(self) -> list[str]:
        """返回当前可用（is_available）的 Provider 名称列表。

        Mock 始终可用；真实 Adapter 需 key 可用。
        """
        return [
            name for name, adapter in self._providers.items()
            if adapter.is_available()
        ]

    # ── 运行时强制切换 ────────────────────────────────

    def force_mock(self, provider_name: str) -> bool:
        """强制该 Provider 走 Mock。始终允许。"""
        if provider_name not in PROVIDER_NAMES:
            raise ValueError(f"未知 Provider: {provider_name}")
        self._overrides[provider_name] = "mock"
        self._providers[provider_name] = MockProviderAdapter(provider_name=provider_name)
        return True

    def force_real(self, provider_name: str) -> bool:
        """强制该 Provider 走真实 Adapter。

        仅在 not dry_run 且 enabled 且 key 可用时允许；否则拒绝（返回 False，不切换）。
        dry_run=true 时必拒绝（dry_run 优先级最高）。
        """
        if provider_name not in PROVIDER_NAMES:
            raise ValueError(f"未知 Provider: {provider_name}")
        if not self._factory.should_use_real(provider_name):
            return False
        self._overrides[provider_name] = "real"
        self._providers[provider_name] = self._factory._REAL_SPECS[provider_name][0](
            api_key=self._factory._key_for(provider_name),
            config=self.config,
        )
        return True

    def clear_override(self, provider_name: str) -> None:
        """清除某 Provider 的强制覆盖，回到配置矩阵决定。"""
        self._overrides.pop(provider_name, None)
        self._providers[provider_name] = self._factory.create_provider(provider_name)

    # ── 配置重载 ──────────────────────────────────────

    def reload_config(self, config: SearchRouterConfig | None = None) -> None:
        """重载配置（None 时从环境变量重新加载），并重建 Provider。

        强制覆盖在重载时清空（回到配置矩阵）。
        """
        self.config = config or SearchRouterConfig.from_env()
        self._factory = ProviderFactory(self.config)
        self._overrides.clear()
        self._build()

    # ── 健康检查（不联网）──────────────────────────────

    def health_check(self) -> dict:
        """健康检查：仅做配置与 Adapter 可用性检查，**不发任何网络请求**。

        Returns:
            dict: 每个 Provider 的健康信息（is_real / is_available / validate_config）。
        """
        result: dict = {
            "dry_run": self.config.dry_run,
            "config_valid": self.config.is_valid(),
            "providers": {},
        }
        for name, adapter in self._providers.items():
            result["providers"][name] = {
                "is_real": is_real_adapter(adapter),
                "is_available": adapter.is_available(),
                "validate_config": adapter.validate_config(),
                "fallback_level": fallback_level_for(name).value,
            }
        return result
