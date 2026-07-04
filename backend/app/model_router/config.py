"""可插拔模型路由配置（设计第四章）。

原则：
- 不押宝单一模型，尤其是免费模型
- V0.1 只定架构不定供应商——provider/model 默认"待定"，M1 施工实测后填充
- 模型选择由任务类型+成本约束+质量要求决定，不人为绑定
- 密钥不入配置结构：真实接入时经环境变量注入（SOP 纪律），本层 mock 阶段无密钥
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .schemas import ModelRole


@dataclass
class RoleConfig:
    """单角色模型配置（设计 4.2 配置结构草案）。"""

    provider: str = "待定"
    model: str = "待定"
    max_tokens: int = 4096
    timeout_seconds: float = 30.0
    cost_per_1k_tokens: Optional[float] = None   # None=待定；免费模型为 0
    max_retries: int = 2                          # 质量不达标打回重试上限（设计 5.1）
    trigger_on: List[str] = field(default_factory=lambda: ["timeout", "quality_fail", "style_drift"])
    purpose: Optional[str] = None
    batch_mode: bool = False
    is_low_cost: bool = False                     # 免费/低成本模型标记 → 硬边界三敏感数据隔离


@dataclass
class ModelRouterConfig:
    """四角色路由配置集。"""

    roles: Dict[ModelRole, RoleConfig] = field(default_factory=dict)
    quality_threshold: float = 60.0               # review 评分 G1 门槛（草案值，M1 施工校准）
    daily_cost_limit: Optional[float] = None      # 单日成本阈值，待 M1 施工时设定
    max_calls_per_content: int = 5                # 单篇文案模型调用次数熔断阈值（硬边界四）

    @classmethod
    def default(cls) -> "ModelRouterConfig":
        """默认配置：四角色齐备，供应商全部待定（mock 阶段）。"""
        return cls(
            roles={
                ModelRole.PRIMARY: RoleConfig(purpose="main_drafting"),
                ModelRole.FALLBACK: RoleConfig(purpose="fallback_takeover"),
                ModelRole.REVIEW: RoleConfig(purpose="structure_check + compliance_pre_scan"),
                ModelRole.REWRITE: RoleConfig(
                    purpose="platform_adaptation + style_polish",
                    batch_mode=True,
                    is_low_cost=True,   # 改写位默认按低成本模型对待，从严执行敏感数据隔离
                ),
            }
        )

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ModelRouterConfig":
        """从 JSON 结构装载（设计 4.2），未知字段忽略。"""
        router = raw.get("model_router", raw)
        cfg = cls.default()
        for role in ModelRole:
            block = router.get(role.value)
            if not isinstance(block, dict):
                continue
            rc = cfg.roles[role]
            for key in (
                "provider", "model", "max_tokens", "timeout_seconds",
                "cost_per_1k_tokens", "max_retries", "trigger_on",
                "purpose", "batch_mode", "is_low_cost",
            ):
                if key in block:
                    setattr(rc, key, block[key])
        for key in ("quality_threshold", "daily_cost_limit", "max_calls_per_content"):
            if key in router:
                setattr(cfg, key, router[key])
        return cfg
