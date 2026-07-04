"""文案加工厂（M1 条件施工 · W1/W2 骨架阶段）。

设计依据：M1 W1 服务骨架与 Brief 接口 + W2 9080 只读召回适配。

本包为纯库层代码：
- 不挂载任何 FastAPI 路由（不开 /content/generate）
- 不发起任何真实网络调用（9080/9200 均 mock）
- 不写 approved / 不 reindex / 不写知识库 / 不写 candidate_pool
- 不部署、不启动服务
- 出口只到 draft_candidate（复用 model_router 约束）

包结构：
- schemas.py：Brief / FactoryTaskState / TraceContext / ContentStagingEntry
- brief.py：Brief 理解层（解析 + 批量输入）
- task_state.py：6 态状态机
- factory.py：工厂主编排骨架
- staging.py：content_staging 私有目录
- recall/：9080 只读召回子包
"""
from .schemas import Brief, ContentStagingEntry, FactoryTaskState, TraceContext
from .brief import BriefParseError, parse_brief, parse_batch_briefs
from .task_state import InvalidTransition, StateMachine, TransitionRecord
from .factory import ContentFactory, FactoryResult
from .staging import ContentStaging

__all__ = [
    "Brief",
    "BriefParseError",
    "ContentFactory",
    "ContentStaging",
    "ContentStagingEntry",
    "FactoryResult",
    "FactoryTaskState",
    "InvalidTransition",
    "StateMachine",
    "TraceContext",
    "TransitionRecord",
    "parse_brief",
    "parse_batch_briefs",
]
