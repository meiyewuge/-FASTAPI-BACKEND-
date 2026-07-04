"""文案加工厂主编排骨架 — 串联 Brief → Recall → bind → Gate → Pack。

设计依据：M1 W1 服务骨架 + Claude Code V2 Patch A。

本层职责边界：
- 骨架编排：Brief → 9080 召回 → bind_materials → 六硬门（W4）→ 打包 → 人审；
- 缺料停单：bind_materials 返回 is_sufficient=False 时停单，不进 PACKAGED；
- 不挂载 FastAPI 路由、不部署、不启动服务；
- 出口只到 draft_candidate（复用 model_router 约束）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.app.model_router.schemas import MissingMaterialReport, TaskType

from .schemas import Brief, ContentStagingEntry, FactoryTaskState, TraceContext
from .staging import ContentStaging
from .task_state import StateMachine
from .recall.binding import bind_materials
from .recall.filters import apply_filters

if TYPE_CHECKING:
    from .recall.client import RecallClient
    from .drafting.generator import DraftGenerator
    from .drafting.schemas import DraftCandidate
    from .gates.pipeline import GatePipeline
    from .gates.schemas import CandidateGateReport


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
    missing_report: Optional[MissingMaterialReport] = None
    draft_candidate: Optional["DraftCandidate"] = None   # W3：三版稿候选（生成器接入时）
    gate_report: Optional["CandidateGateReport"] = None  # W4：六硬门候选裁决（pipeline 接入时）


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
    draft_generator: Optional["DraftGenerator"] = None   # W3：注入即启用三版稿生成
    gate_pipeline: Optional["GatePipeline"] = None       # W4：注入即启用六硬门裁决

    def process_brief(self, brief: Brief) -> FactoryResult:
        """处理单条 Brief → FactoryResult（骨架编排 + 缺料停单）。

        链路：Brief → 召回 → bind_materials → 出稿 → 门检 → 打包 → staging
        缺料时：bind_materials.is_sufficient=False → 停单（HALTED_MISSING_MATERIALS）
        """
        trace = TraceContext.from_brief(brief)
        content_id = f"content_{uuid.uuid4().hex[:12]}"
        sm = StateMachine()

        # Step 1: queued → producing
        sm.transition(FactoryTaskState.PRODUCING, operator="factory")

        # Step 2: 9080 只读召回（W2 实现）
        recall_summary: Dict[str, Any] = {"status": "mock", "materials_count": 0}
        used_materials_ids: List[str] = []

        # Patch D: recall_client=None 时直接停单，不绕过缺料判定
        if self.recall_client is None:
            sm.transition(
                FactoryTaskState.HALTED_MISSING_MATERIALS,
                operator="factory",
                note="缺料停单：未配置召回客户端",
            )
            return FactoryResult(
                content_id=content_id,
                state=sm.current,
                brief_id=brief.brief_id,
                trace_id=trace.trace_id,
                text=None,
                used_materials_ids=[],
                recall_summary={"status": "recall_client_not_configured", "materials_count": 0},
                missing_report=MissingMaterialReport(
                    content_id=f"pending_{brief.brief_id}",
                    task_type=brief.task_type,
                    missing_material_types=["recall_client_not_configured"],
                    suggested_recall_keywords=[],
                ),
            )

        from .recall.client import RecallQuery
        query = RecallQuery(
            brief_id=brief.brief_id,
            keywords=brief.raw_text.split()[:5],
            material_types=None,
            max_results=10,
        )
        recall_result = self.recall_client.recall(query)

        # Patch C: 对召回素材应用白名单/黑名单过滤
        filtered_materials = apply_filters(recall_result.materials)
        recall_result.materials = filtered_materials

        recall_summary = {
            "status": recall_result.status.value,
            "materials_count": len(recall_result.materials),
        }

        # TODO(W6): 接入 RecallLog 记录每次召回

        # Step 2.5: 缺料停单判定（Patch A）
        bound = bind_materials(recall_result, brief)
        if not bound.is_sufficient:
            # 缺料停单：不进 GATED / PACKAGED / staging 候选态
            sm.transition(
                FactoryTaskState.HALTED_MISSING_MATERIALS,
                operator="factory",
                note="缺料停单：素材不足，不出稿",
            )
            return FactoryResult(
                content_id=content_id,
                state=sm.current,
                brief_id=brief.brief_id,
                trace_id=trace.trace_id,
                text=None,
                used_materials_ids=[],
                recall_summary=recall_summary,
                missing_report=bound.missing_report,
            )
        used_materials_ids = bound.material_ids

        # Step 3: 草稿生成与模型路由接线（W3）
        # 未注入 draft_generator → 保持 W1/W2 骨架行为（text=None）；
        # 注入后 → 生成三版稿候选，且只有 used_materials 充分时才走到这里。
        text: Optional[str] = None
        draft_candidate: Optional["DraftCandidate"] = None
        if self.draft_generator is not None:
            draft_candidate = self.draft_generator.generate(
                content_id=content_id,
                brief_id=brief.brief_id,
                trace_id=trace.trace_id,
                brief_text=brief.raw_text,
                used_materials=bound.materials,
                platform=brief.target_platform,
                risk_hint=brief.risk_hint,
            )
            from .drafting.schemas import DraftCandidateStatus
            if draft_candidate.status == DraftCandidateStatus.BLOCKED:
                # 三版稿全被无源事实句/模型新增事实拦截 → 候选拦截终态，不写 staging
                sm.transition(
                    FactoryTaskState.BLOCKED_DRAFT,
                    operator="factory",
                    note="三版稿全被拦：无源事实句/模型新增事实",
                )
                return FactoryResult(
                    content_id=content_id,
                    state=sm.current,
                    brief_id=brief.brief_id,
                    trace_id=trace.trace_id,
                    text=None,
                    used_materials_ids=used_materials_ids,
                    recall_summary=recall_summary,
                    draft_candidate=draft_candidate,
                )
            # 至少一版 OK：取首个 OK 版作为主展示文本
            ok = draft_candidate.ok_versions
            text = ok[0].text if ok else None

        # Step 4: 六硬门候选裁决（W4）
        # 未注入 gate_pipeline → 保持 W3 骨架行为（直接进 GATED→PACKAGED）；
        # 注入后 → 对三版稿逐版跑 G1-G6 + ≤3 圈 loop，按裁决结论决定去向。
        sm.transition(FactoryTaskState.GATED, operator="factory")
        gate_report: Optional["CandidateGateReport"] = None
        if self.gate_pipeline is not None and draft_candidate is not None:
            from .gates.schemas import CandidateReviewStatus
            gate_report = self.gate_pipeline.run(
                draft_candidate,
                platform=brief.target_platform,
                line=brief.line,
                g3_materials=bound.materials,
            )
            if gate_report.review_status == CandidateReviewStatus.BLOCKED:
                # 六硬门后无任何可用版本 → 门拦截终态，不写 staging、不打包
                sm.transition(
                    FactoryTaskState.GATE_BLOCKED,
                    operator="factory",
                    note="六硬门后无可用版本",
                )
                return FactoryResult(
                    content_id=content_id,
                    state=sm.current,
                    brief_id=brief.brief_id,
                    trace_id=trace.trace_id,
                    text=None,
                    used_materials_ids=used_materials_ids,
                    recall_summary=recall_summary,
                    draft_candidate=draft_candidate,
                    gate_report=gate_report,
                )

        # Step 5: 打包（conditional_pass/needs_human_review 仍进人审，不自动发布）
        # TODO(W5): package = pack_for_review(...) — 审读包前置结构见 gates.review_package
        sm.transition(FactoryTaskState.PACKAGED, operator="factory")

        # Step 6: 写入 staging（候选态，绝不写 approved / 不发布）
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
            draft_candidate=draft_candidate,
            gate_report=gate_report,
        )
