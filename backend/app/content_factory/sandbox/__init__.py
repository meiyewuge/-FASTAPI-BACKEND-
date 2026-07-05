"""W8 联调沙盒骨架（M1 条件施工 · mock）。

设计依据：M1-W8 条件施工许可。

本包职责：
- 串联 W1-W7 全部子包，在全 mock 环境下跑完整产线链路；
- 验证 Brief → Recall → Draft → Gates → MidPlatform → Observability → Rulepack 全通；
- 不接真实 9080/9200/DB/监控/模型/发布池；
- sandbox pass ≠ 生产可用（严禁 20）。
"""
from .schemas import SandboxPathKind, SandboxResult
from .runner import SandboxRunner
from .fixtures import build_sandbox_runner
from .contracts import (
    validate_feature_flags,
    validate_readiness_checklists,
    validate_rulepacks,
)

__all__ = [
    "SandboxPathKind",
    "SandboxResult",
    "SandboxRunner",
    "build_sandbox_runner",
    "validate_feature_flags",
    "validate_readiness_checklists",
    "validate_rulepacks",
]
