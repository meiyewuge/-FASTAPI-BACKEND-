"""pytest 配置和 fixtures。"""

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from search_router.config import SearchRouterConfig
from search_router.models.search_request import SearchRequest, TaskType
from search_router.adapters.mock import MockProviderAdapter


@pytest.fixture
def default_config() -> SearchRouterConfig:
    """默认配置（dry_run=true）。"""
    return SearchRouterConfig.from_env()


@pytest.fixture
def mock_request() -> SearchRequest:
    """标准 Mock 搜索请求。"""
    return SearchRequest(
        query="美业AI趋势",
        task_type=TaskType.CHINESE_INDUSTRY_NEWS,
        max_results=5,
    )


@pytest.fixture
def mock_adapter() -> MockProviderAdapter:
    """Mock Provider Adapter 实例。"""
    return MockProviderAdapter()
