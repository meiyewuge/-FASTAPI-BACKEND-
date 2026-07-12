"""配置加载与校验。

从环境变量读取所有配置，支持 .env 文件 fallback。
dry_run=true 时强制所有 Provider 走 Mock。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    # python-dotenv 可选，有则加载 .env
    from dotenv import load_dotenv
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False


def _str_to_bool(val: str | None, default: bool = False) -> bool:
    """将环境变量字符串转为 bool。"""
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


def _str_to_float(val: str | None, default: float) -> float:
    """将环境变量字符串转为 float。"""
    if val is None:
        return default
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return default


def _str_to_int(val: str | None, default: int) -> int:
    """将环境变量字符串转为 int。"""
    if val is None:
        return default
    try:
        return int(val.strip())
    except (ValueError, TypeError):
        return default


@dataclass
class SearchRouterConfig:
    """Search Router 全局配置。

    所有字段从环境变量读取，未设置时使用默认值。
    dry_run=true 时强制所有 Provider 走 Mock，不调任何真实 API。
    """

    # ---- 运行模式 ----
    dry_run: bool = True

    # ---- Provider 开关 ----
    provider_mock_enabled: bool = True
    provider_bocha_enabled: bool = False
    provider_glm_search_enabled: bool = False
    provider_tavily_enabled: bool = False

    # ---- LLM 增强 ----
    glm_enhancer_enabled: bool = False

    # ---- 成本熔断阈值（¥）----
    cost_limit_single_task: float = 2.0
    cost_limit_daily: float = 30.0
    cost_limit_monthly: float = 300.0
    cost_limit_provider_daily: float = 10.0
    provider_max_consecutive_failures: int = 3

    # ---- 搜索参数 ----
    max_search_results: int = 20
    max_candidate_cards: int = 10

    # ---- 日志 ----
    log_desensitize: bool = True
    log_level: str = "INFO"

    # ---- Publish Time Enricher ----
    publish_time_enricher_enabled: bool = False
    publish_time_enricher_shadow_only: bool = True
    publish_time_enricher_max_batch: int = 10
    publish_time_enricher_max_concurrent: int = 3
    publish_time_enricher_max_per_domain: int = 1
    publish_time_enricher_total_timeout: float = 15.0
    publish_time_enricher_max_response_bytes: int = 524288
    publish_time_enricher_max_redirects: int = 2

    # ---- API Key（P0 Phase 1 不使用）----
    bocha_api_key: str = ""
    zhipu_api_key: str = ""
    tavily_api_key: str = ""

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "SearchRouterConfig":
        """从环境变量加载配置。支持可选的 .env 文件 fallback。

        Args:
            env_file: .env 文件路径。如果未提供，尝试从当前目录加载 .env。
        """
        # 如果有 python-dotenv，加载 .env 文件
        if _HAS_DOTENV:
            if env_file:
                load_dotenv(env_file)
            else:
                load_dotenv()  # 默认加载当前目录 .env

        return cls(
            # 运行模式
            dry_run=_str_to_bool(os.getenv("SEARCH_ROUTER_DRY_RUN"), True),

            # Provider 开关
            provider_mock_enabled=_str_to_bool(os.getenv("PROVIDER_MOCK_ENABLED"), True),
            provider_bocha_enabled=_str_to_bool(os.getenv("PROVIDER_BOCHA_ENABLED"), False),
            provider_glm_search_enabled=_str_to_bool(os.getenv("PROVIDER_GLM_SEARCH_ENABLED"), False),
            provider_tavily_enabled=_str_to_bool(os.getenv("PROVIDER_TAVILY_ENABLED"), False),

            # LLM 增强
            glm_enhancer_enabled=_str_to_bool(os.getenv("GLM_ENHANCER_ENABLED"), False),

            # 成本熔断
            cost_limit_single_task=_str_to_float(os.getenv("COST_LIMIT_SINGLE_TASK"), 2.0),
            cost_limit_daily=_str_to_float(os.getenv("COST_LIMIT_DAILY"), 30.0),
            cost_limit_monthly=_str_to_float(os.getenv("COST_LIMIT_MONTHLY"), 300.0),
            cost_limit_provider_daily=_str_to_float(os.getenv("COST_LIMIT_PROVIDER_DAILY"), 10.0),
            provider_max_consecutive_failures=_str_to_int(
                os.getenv("PROVIDER_MAX_CONSECUTIVE_FAILURES"), 3
            ),

            # 搜索参数
            max_search_results=_str_to_int(os.getenv("MAX_SEARCH_RESULTS"), 20),
            max_candidate_cards=_str_to_int(os.getenv("MAX_CANDIDATE_CARDS"), 10),

            # 日志
            log_desensitize=_str_to_bool(os.getenv("LOG_DESENSITIZE"), True),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip() or "INFO",

            # API Key（P0 Phase 1 不使用，仅读取占位）
            # ZHIPU_API_KEY 为主字段，兼容旧字段 GLM_API_KEY（deprecated）
            bocha_api_key=os.getenv("BOCHA_API_KEY", ""),
            zhipu_api_key=os.getenv("ZHIPU_API_KEY") or os.getenv("GLM_API_KEY", ""),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),

            # Publish Time Enricher
            publish_time_enricher_enabled=_str_to_bool(os.getenv("PUBLISH_TIME_ENRICHER_ENABLED"), False),
            publish_time_enricher_shadow_only=_str_to_bool(os.getenv("PUBLISH_TIME_ENRICHER_SHADOW_ONLY"), True),
            publish_time_enricher_max_batch=_str_to_int(os.getenv("PUBLISH_TIME_ENRICHER_MAX_BATCH"), 10),
            publish_time_enricher_max_concurrent=_str_to_int(os.getenv("PUBLISH_TIME_ENRICHER_MAX_CONCURRENT"), 3),
            publish_time_enricher_max_per_domain=_str_to_int(os.getenv("PUBLISH_TIME_ENRICHER_MAX_PER_DOMAIN"), 1),
            publish_time_enricher_total_timeout=_str_to_float(os.getenv("PUBLISH_TIME_ENRICHER_TOTAL_TIMEOUT"), 15.0),
            publish_time_enricher_max_response_bytes=_str_to_int(os.getenv("PUBLISH_TIME_ENRICHER_MAX_RESPONSE_BYTES"), 524288),
            publish_time_enricher_max_redirects=_str_to_int(os.getenv("PUBLISH_TIME_ENRICHER_MAX_REDIRECTS"), 2),
        )

    def validate(self) -> list[str]:
        """校验配置合法性，返回错误信息列表（空列表 = 全部通过）。"""
        errors: list[str] = []

        # 成本阈值必须为正数
        if self.cost_limit_single_task <= 0:
            errors.append("cost_limit_single_task 必须 > 0")
        if self.cost_limit_daily <= 0:
            errors.append("cost_limit_daily 必须 > 0")
        if self.cost_limit_monthly <= 0:
            errors.append("cost_limit_monthly 必须 > 0")
        if self.cost_limit_provider_daily <= 0:
            errors.append("cost_limit_provider_daily 必须 > 0")

        # 成本阈值逻辑关系
        if self.cost_limit_single_task >= self.cost_limit_daily:
            errors.append("cost_limit_single_task 必须 < cost_limit_daily")
        if self.cost_limit_daily >= self.cost_limit_monthly:
            errors.append("cost_limit_daily 必须 < cost_limit_monthly")

        # 搜索参数
        if self.max_search_results <= 0 or self.max_search_results > 100:
            errors.append("max_search_results 必须在 1~100 之间")
        if self.max_candidate_cards <= 0 or self.max_candidate_cards > 50:
            errors.append("max_candidate_cards 必须在 1~50 之间")

        # dry_run=true 时强制所有真实 Provider 关闭
        if self.dry_run:
            if self.provider_bocha_enabled:
                errors.append("dry_run=true 时 provider_bocha_enabled 必须为 false")
            if self.provider_glm_search_enabled:
                errors.append("dry_run=true 时 provider_glm_search_enabled 必须为 false")
            if self.provider_tavily_enabled:
                errors.append("dry_run=true 时 provider_tavily_enabled 必须为 false")
            if self.glm_enhancer_enabled:
                errors.append("dry_run=true 时 glm_enhancer_enabled 必须为 false")

        # Enricher 参数边界校验
        if self.publish_time_enricher_max_batch < 1 or self.publish_time_enricher_max_batch > 50:
            errors.append("publish_time_enricher_max_batch 必须在 1~50 之间")
        if self.publish_time_enricher_max_concurrent < 1 or self.publish_time_enricher_max_concurrent > 10:
            errors.append("publish_time_enricher_max_concurrent 必须在 1~10 之间")
        if self.publish_time_enricher_max_per_domain < 1 or self.publish_time_enricher_max_per_domain > 5:
            errors.append("publish_time_enricher_max_per_domain 必须在 1~5 之间")
        if self.publish_time_enricher_total_timeout < 1.0 or self.publish_time_enricher_total_timeout > 60:
            errors.append("publish_time_enricher_total_timeout 必须在 0~60 之间")
        if self.publish_time_enricher_max_response_bytes < 1024 or self.publish_time_enricher_max_response_bytes > 1048576:
            errors.append("publish_time_enricher_max_response_bytes 必须在 1024~1048576 之间")
        if self.publish_time_enricher_max_redirects < 0 or self.publish_time_enricher_max_redirects > 5:
            errors.append("publish_time_enricher_max_redirects 必须在 0~5 之间")

        return errors

    def is_valid(self) -> bool:
        """配置是否合法。"""
        return len(self.validate()) == 0

    def should_use_mock(self) -> bool:
        """是否应使用 Mock Provider。

        dry_run=true 时强制走 Mock。
        dry_run=false 时如果所有真实 Provider 都未启用也走 Mock。
        """
        if self.dry_run:
            return True
        return not (
            self.provider_bocha_enabled
            or self.provider_glm_search_enabled
            or self.provider_tavily_enabled
        )

    def should_use_real_enhancer(self) -> bool:
        """三锁判断：只有三者同时满足才允许真实 GLM 增强。

        1. SEARCH_ROUTER_DRY_RUN=false
        2. PROVIDER_GLM_SEARCH_ENABLED=true
        3. GLM_ENHANCER_ENABLED=true
        """
        return (
            not self.dry_run
            and self.provider_glm_search_enabled
            and self.glm_enhancer_enabled
        )

    def to_dict(self, safe: bool = True) -> dict:
        """输出 dict。safe=True 时对 API Key 脱敏。"""
        d = {
            "dry_run": self.dry_run,
            "provider_mock_enabled": self.provider_mock_enabled,
            "provider_bocha_enabled": self.provider_bocha_enabled,
            "provider_glm_search_enabled": self.provider_glm_search_enabled,
            "provider_tavily_enabled": self.provider_tavily_enabled,
            "glm_enhancer_enabled": self.glm_enhancer_enabled,
            "cost_limit_single_task": self.cost_limit_single_task,
            "cost_limit_daily": self.cost_limit_daily,
            "cost_limit_monthly": self.cost_limit_monthly,
            "cost_limit_provider_daily": self.cost_limit_provider_daily,
            "provider_max_consecutive_failures": self.provider_max_consecutive_failures,
            "max_search_results": self.max_search_results,
            "max_candidate_cards": self.max_candidate_cards,
            "log_desensitize": self.log_desensitize,
            "log_level": self.log_level,
            "publish_time_enricher_enabled": self.publish_time_enricher_enabled,
            "publish_time_enricher_shadow_only": self.publish_time_enricher_shadow_only,
            "publish_time_enricher_max_batch": self.publish_time_enricher_max_batch,
            "publish_time_enricher_max_concurrent": self.publish_time_enricher_max_concurrent,
            "publish_time_enricher_max_per_domain": self.publish_time_enricher_max_per_domain,
            "publish_time_enricher_total_timeout": self.publish_time_enricher_total_timeout,
            "publish_time_enricher_max_response_bytes": self.publish_time_enricher_max_response_bytes,
            "publish_time_enricher_max_redirects": self.publish_time_enricher_max_redirects,
        }
        if safe:
            from search_router.logger import desensitize_key
            d["bocha_api_key"] = desensitize_key(self.bocha_api_key) if self.bocha_api_key else ""
            d["zhipu_api_key"] = desensitize_key(self.zhipu_api_key) if self.zhipu_api_key else ""
            d["tavily_api_key"] = desensitize_key(self.tavily_api_key) if self.tavily_api_key else ""
        else:
            d["bocha_api_key"] = self.bocha_api_key
            d["zhipu_api_key"] = self.zhipu_api_key
            d["tavily_api_key"] = self.tavily_api_key
        return d
