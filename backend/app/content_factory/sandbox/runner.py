"""W8 联调沙盒 Runner — 串联 W1-W7 全链路 mock。

设计依据：M1-W8 条件施工许可 二.2/二.4/二.5。

编排链路：
  Brief → ContentFactory.process_brief
        → MidPlatformMock.ingest_factory_result
        → ProductionLineObserver.observe
        → 构造 SandboxResult

日报路径：
  多条 factory result 累积 → build_daily_report → MockReportStore.save_report

严禁：
- 不接真实 9080/9200/DB/监控/模型/发布池；
- 不写 approved / 不发布 / 不 reindex；
- 不挂 FastAPI 路由；
- sandbox pass ≠ 生产可用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.app.content_factory.brief import parse_brief
from backend.app.content_factory.drafting.generator import DraftGenerator
from backend.app.content_factory.factory import ContentFactory, FactoryResult
from backend.app.content_factory.gates.pipeline import GatePipeline
from backend.app.content_factory.midplatform.pages import MidPlatformMock
from backend.app.content_factory.midplatform.schemas import CandidateReviewEntry
from backend.app.content_factory.obs_contracts.mocks import (
    MockAlertSink,
    MockReportStore,
    MockScheduler,
)
from backend.app.content_factory.observability.observer import ProductionLineObserver
from backend.app.content_factory.observability.report import build_daily_report
from backend.app.content_factory.observability.schemas import DailyReport
from backend.app.content_factory.recall.client import MockRecallClient
from backend.app.content_factory.schemas import Brief, FactoryTaskState

from .schemas import SandboxPathKind, SandboxResult


@dataclass
class SandboxRunner:
    """联调沙盒主编排器。

    持有 W1-W7 全部 mock 组件，串联完整产线链路。
    全部内存 mock，不接真实服务。
    """

    recall_client: MockRecallClient
    draft_generator: DraftGenerator
    gate_pipeline: GatePipeline
    midplatform: MidPlatformMock
    observer: ProductionLineObserver
    report_store: MockReportStore
    scheduler: MockScheduler
    alert_sink: MockAlertSink
    # ── 运行结果累积 ──
    results: List[SandboxResult] = field(default_factory=list)
    factory_results: List[FactoryResult] = field(default_factory=list)

    # ──────────────────────────────────────────────────────────────────
    # 主入口：单次运行
    # ──────────────────────────────────────────────────────────────────
    def run_brief(self, brief_dict: Dict[str, Any]) -> SandboxResult:
        """解析 Brief → factory → midplatform → observer → SandboxResult。"""
        brief = parse_brief(brief_dict)
        return self._run(brief)

    def run_raw_brief(self, brief: Brief) -> SandboxResult:
        """直接传入 Brief 对象（跳过 parse）。"""
        return self._run(brief)

    def _run(self, brief: Brief) -> SandboxResult:
        """内部编排：factory → midplatform → observer → result。"""
        # Step 1: 构造 ContentFactory 并跑
        factory = ContentFactory(
            recall_client=self.recall_client,
            draft_generator=self.draft_generator,
            gate_pipeline=self.gate_pipeline,
        )
        fr = factory.process_brief(brief)
        self.factory_results.append(fr)

        # Step 2: 中台分流
        ingest_result = self.midplatform.ingest_factory_result(fr)

        # Step 3: 观测
        self.observer.observe(fr)
        # 快照审读队列
        self.observer.snapshot_review_queue(self.midplatform.queue)

        # Step 4: 构造 SandboxResult
        path = self._classify_path(fr, ingest_result)
        review_queue_state = None
        if isinstance(ingest_result, CandidateReviewEntry):
            review_queue_state = ingest_result.state.value

        sr = SandboxResult(
            path=path,
            factory_state=fr.state,
            content_id=fr.content_id,
            brief_id=fr.brief_id,
            trace_id=fr.trace_id,
            text=fr.text,
            recall_summary=fr.recall_summary,
            used_materials_ids=fr.used_materials_ids,
            gate_review_status=(
                fr.gate_report.review_status.value if fr.gate_report else None
            ),
            review_queue_state=review_queue_state,
        )
        self.results.append(sr)
        return sr

    # ──────────────────────────────────────────────────────────────────
    # 日报路径
    # ──────────────────────────────────────────────────────────────────
    def build_report(self, day: Optional[str] = None) -> DailyReport:
        """从观测器聚合日报并存入 MockReportStore。"""
        report = build_daily_report(self.observer, day=day)
        self.report_store.save_report(report)
        return report

    # ──────────────────────────────────────────────────────────────────
    # 路径分类
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _classify_path(fr: FactoryResult, ingest_result) -> SandboxPathKind:
        """根据 factory 终态 + 中台结果判定沙盒路径分类。"""
        if fr.state == FactoryTaskState.HALTED_MISSING_MATERIALS:
            return SandboxPathKind.MISSING_MATERIALS
        if fr.state == FactoryTaskState.BLOCKED_DRAFT:
            return SandboxPathKind.BLOCKED_DRAFT
        if fr.state == FactoryTaskState.GATE_BLOCKED:
            return SandboxPathKind.GATE_BLOCKED
        if fr.state == FactoryTaskState.PACKAGED:
            # 检查中台是否入队且为 needs_human_review
            if isinstance(ingest_result, CandidateReviewEntry):
                state_val = ingest_result.state.value
                if state_val in ("needs_human_review", "must_sign"):
                    return SandboxPathKind.HUMAN_REVIEW
            return SandboxPathKind.SUCCESS
        return SandboxPathKind.SUCCESS

    # ──────────────────────────────────────────────────────────────────
    # 只读统计
    # ──────────────────────────────────────────────────────────────────
    def summary(self) -> Dict[str, Any]:
        """沙盒运行汇总（路径分布 + 观测指标 + 日报快照）。"""
        by_path: Dict[str, int] = {}
        for r in self.results:
            by_path[r.path.value] = by_path.get(r.path.value, 0) + 1
        return {
            "total_runs": len(self.results),
            "by_path": by_path,
            "observer_run_count": self.observer.run_count,
            "observer_brief_count": self.observer.brief_count,
            "review_queue_total": self.midplatform.queue.count(),
            "notice_count": len(self.midplatform.notices),
            "report_store_dates": self.report_store.list_dates(),
            "scheduler_jobs": len(self.scheduler.list_jobs()),
            "alert_sink_pending": len(self.alert_sink._alerts),
        }
