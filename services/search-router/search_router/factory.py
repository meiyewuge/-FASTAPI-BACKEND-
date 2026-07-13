"""ProviderFactory — Provider 实例化与 mock/real 切换矩阵（T2B）。

切换矩阵（dry_run 优先级最高）：
    dry_run=true,  任意开关                          → 全 Mock
    dry_run=false, BOCHA/GLM/TAVILY 全 false         → 全 Mock
    dry_run=false, BOCHA=true 其余 false             → Bocha Real，其余 Mock
    dry_run=false, BOCHA=true,GLM=true,TAVILY=false  → Bocha+GLM Real，其余 Mock
    dry_run=false, 三者全 true                        → 全 Real
    dry_run=false, 仅 GLM=true                        → 仅 GLM Real

铁律：
    - dry_run=true 时即使 API Key 存在也必须全 Mock。
    - 「真实」需同时满足：not dry_run 且 provider enabled 且 key 可用。
    - 不得因环境变量里存在 Key 就自动真实调用。
    - 本阶段真实 Adapter 也不联网（dry_run 默认即 Mock；真实路径需显式三条件）。
"""

from __future__ import annotations

from search_router.config import SearchRouterConfig
from search_router.adapters.base import BaseProviderAdapter
from search_router.adapters.mock import MockProviderAdapter
from search_router.adapters.bocha import BochaAdapter
from search_router.adapters.glm_search import GLMSearchAdapter
from search_router.adapters.tavily import TavilyAdapter
from search_router.models.search_response import ProviderType


# 三个真实 Provider 槽位
PROVIDER_NAMES = ("bocha", "glm_search", "tavily")


def is_real_adapter(adapter: BaseProviderAdapter) -> bool:
    """是否为真实 Adapter（Mock 的 provider_type 为 MOCK）。"""
    return adapter.provider_type != ProviderType.MOCK


class ProviderFactory:
    """根据配置创建 Provider Adapter，执行 mock/real 切换矩阵。"""

    # provider_name -> (真实 Adapter 类, config 上的 key 字段名)
    _REAL_SPECS = {
        "bocha": (BochaAdapter, "bocha_api_key"),
        "glm_search": (GLMSearchAdapter, "zhipu_api_key"),
        "tavily": (TavilyAdapter, "tavily_api_key"),
    }

    # provider_name -> config 上的 enabled 字段名
    _ENABLED_FIELDS = {
        "bocha": "provider_bocha_enabled",
        "glm_search": "provider_glm_search_enabled",
        "tavily": "provider_tavily_enabled",
    }

    def __init__(self, config: SearchRouterConfig | None = None) -> None:
        self.config = config or SearchRouterConfig()

    # ── 单个判断 ──────────────────────────────────────

    def _key_for(self, provider_name: str) -> str:
        _, key_field = self._REAL_SPECS[provider_name]
        return getattr(self.config, key_field, "") or ""

    def _enabled(self, provider_name: str) -> bool:
        return bool(getattr(self.config, self._ENABLED_FIELDS[provider_name], False))

    def should_use_real(self, provider_name: str) -> bool:
        """该 Provider 是否应使用真实 Adapter。

        三条件全满足才为真实：not dry_run 且 enabled 且 key 非空。
        dry_run=true 时永远为 False（优先级最高）。
        """
        if self.config.dry_run:
            return False
        if not self._enabled(provider_name):
            return False
        return bool(self._key_for(provider_name).strip())

    # ── 创建 ──────────────────────────────────────────

    def create_provider(self, provider_name: str) -> BaseProviderAdapter:
        """创建单个 Provider Adapter（真实或 Mock）。"""
        if provider_name not in self._REAL_SPECS:
            raise ValueError(f"未知 Provider: {provider_name}")

        if self.should_use_real(provider_name):
            adapter_cls, _ = self._REAL_SPECS[provider_name]
            return adapter_cls(api_key=self._key_for(provider_name), config=self.config)

        # 否则回退 Mock（保留 provider_name 以便上层识别槽位）
        return MockProviderAdapter(provider_name=provider_name)

    def create_providers(self) -> dict[str, BaseProviderAdapter]:
        """按切换矩阵创建全部三个 Provider。"""
        return {name: self.create_provider(name) for name in PROVIDER_NAMES}
