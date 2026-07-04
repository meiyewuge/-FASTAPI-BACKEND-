"""文案加工厂主编排骨架 — 串联 Brief → Recall → ModelRouter → Gate。

设计依据：M1 W1 服务骨架。

本层职责边界：
- 骨架编排：Brief → 9080 召回 → 模型路由 → 六硬门（W4）→ 打包 → 人审；
- 当前为骨架阶段，每步留 TODO 注释，不实现真实业务逻辑；
- 不挂载 FastAPI 路由、不部署、不启动服务；
- 出口只到 draft_candidate（复用 model_router 约束）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.app.model_router.schemas import TaskType

from .schemas import Brief, ContentStagingEntry, FactoryTaskState, TraceContext
from .staging import ContentStaging
from .task_state import StateMachine

if TYPE_CHECKING:
    from .recall.client import RecallClient


# ──────────────────────────────────────────────────────────────────────
# 工厂输出
# ──────────────────────────────────────────────────────────────────────
@dataclass
class FactoryResult:
    """工厂单次处理结果。"""

    content_id: str
    state: FactoryTaskState
    brief_id: str
    trace_id: str
    text: Optional[str] = None
    used_materials_ids: List[str] = field(default_factory=list)
    recall_summary: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# 工厂主编排
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ContentFactory:
    """文案加工厂主编排骨架。

    持有 recall_client / staging 引用，串联完整生产链路。
    当前为 mock 阶段：每步以 TODO 注释标记后续工单接入点。
    """

    recall_client: Optional["RecallClient"] = None
    staging: ContentStaging = field(default_factory=ContentStaging)

    def process_brief(self, brief: Brief) -> FactoryResult:
        """处理单条 Brief → FactoryResult（骨架编排）。

        链路：Brief → 召回 → 出稿 → 门检 → 打包 → staging
        """
        trace = TraceContext.from_brief(brief)
        content_id = f"content_{uuid.uuid4().hex[:12]}"
        sm = StateMachine()

        # Step 1: queued → producing
        sm.transition(FactoryTaskState.PRODUCING, operator="factory")

        # Step 2: 9080 只读召回（W2 实现）
        # TODO(W2): recall_result = self.recall_client.recall(RecallQuery(...))
        recall_summary: Dict[str, Any] = {"status": "mock", "materials_count": 0}
        used_materials_ids: List[str] = []

        if self.recall_client is not None:
            from .recall.client import RecallQuery
            query = RecallQuery(
                brief_id=brief.brief_id,
                keywords=brief.raw_text.split()[:5],
                material_types=None,
                max_results=10,
            )
            recall_result = self.recall_client.recall(query)
            recall_summary = {
                "status": recall_result.status.value,
                "materials_count": len(recall_result.materials),
            }
            used_materials_ids = [m.get("id", "") for m in recall_result.materials if m.get("id")]

        # Step 3: 模型路由出稿（W0.5 已实现，此处骨架调用）
        # TODO(W1+): draft = model_router.generate_draft(DraftTask(...))
        text = None

        # Step 4: 六硬门质检（W4 工单实现后激活）
        # TODO(W4): gate_results = gate_pipeline(text, task)
        sm.transition(FactoryTaskState.GATED, operator="factory")

        # Step 5: 打包
        # TODO(W3): package = pack_for_review(text, gate_results, used_materials)
        sm.transition(FactoryTaskState.PACKAGED, operator="factory")

        # Step 6: 写入 staging
        entry = ContentStagingEntry(
            content_id=content_id,
            brief_id=brief.brief_id,
            trace_id=trace.trace_id,
            state=sm.current,
            text=text,
            used_materials_ids=used_materials_ids,
        )
        self.staging.put(entry)

        return FactoryResult(
            content_id=content_id,
            state=sm.current,
            brief_id=brief.brief_id,
            trace_id=trace.trace_id,
            text=text,
            used_materials_ids=used_materials_ids,
            recall_summary=recall_summary,
        )
