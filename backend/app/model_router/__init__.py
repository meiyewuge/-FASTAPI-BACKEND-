"""模型路由与兜底层（M1 条件施工 · mock 阶段）。

依据《模型路由与兜底层设计 V0.1》(docs/M1/MODEL_ROUTER_AND_FALLBACK_DESIGN_V0_1.md)。

核心公式：库负责"真"，模型负责"会写"，合规门负责"不能乱"，人负责"值不值得发"。

本包为纯库层代码：
- 不挂载任何 FastAPI 路由（不开 /content/generate）
- 不发起任何真实模型调用（仅 MockModelClient，供应商 M1 施工阶段实测后填充）
- 出口只到 draft_candidate（候选态），publish_allowed 恒为 False
- 不写 approved、不自动发布、不接 9200
"""
from .schemas import (
    DraftTask,
    GateResult,
    MissingMaterialReport,
    ModelRole,
    RouterResult,
    TaskStatus,
    TaskType,
)
from .config import ModelRouterConfig, RoleConfig
from .clients import MockModelClient, ModelClient, ModelReply
from .router import ModelRouter
from .call_log import CallLog
from .circuit_breaker import CircuitBreaker, CircuitOpenError

__all__ = [
    "CallLog",
    "CircuitBreaker",
    "CircuitOpenError",
    "DraftTask",
    "GateResult",
    "MissingMaterialReport",
    "MockModelClient",
    "ModelClient",
    "ModelReply",
    "ModelRole",
    "ModelRouter",
    "ModelRouterConfig",
    "RoleConfig",
    "RouterResult",
    "TaskStatus",
    "TaskType",
]
