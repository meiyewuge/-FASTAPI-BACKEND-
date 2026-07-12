"""BaseProviderAdapter — 所有 Provider Adapter 的抽象基类。

定义统一接口：
    provider_name: str (abstract property)
    provider_type: ProviderType (abstract property)
    is_available() -> bool
    async search(request: SearchRequest) -> SearchResponse
    estimate_cost(request: SearchRequest) -> float
    validate_config() -> bool
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from search_router.models.search_request import SearchRequest
from search_router.models.search_response import SearchResponse, ProviderType


class BaseProviderAdapter(ABC):
    """Provider Adapter 抽象基类。

    所有 Provider（Mock / Bocha / GLM / Tavily / Codeact）必须继承此类。
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 名称（mock / bocha / glm_search / tavily / codeact）。"""
        ...

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Provider 类型（MOCK / PRIMARY / FALLBACK / EMERGENCY）。"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Provider 是否可用。

        Mock Provider 始终可用。
        真实 Provider 需检查 API Key 是否配置、是否在 dry_run 模式等。
        """
        ...

    @abstractmethod
    async def search(self, request: SearchRequest) -> SearchResponse:
        """执行搜索。

        Args:
            request: 搜索请求

        Returns:
            SearchResponse: 搜索响应
        """
        ...

    @abstractmethod
    def estimate_cost(self, request: SearchRequest) -> float:
        """预估单次搜索成本（¥）。

        Mock Provider 返回 0.0。
        真实 Provider 按定价估算。

        Args:
            request: 搜索请求

        Returns:
            预估成本（¥）
        """
        ...

    @abstractmethod
    def validate_config(self) -> bool:
        """校验 Provider 配置是否合法。

        Mock Provider 始终返回 True。
        真实 Provider 需检查 API Key 格式、端点 URL 等。

        Returns:
            配置是否合法
        """
        ...
