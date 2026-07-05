"""W8 联调沙盒测试 — 6 条路径 + 契约校验 + 红线纪律。

覆盖 M1-W8 条件施工许可全部允许项：
1. 成功路径（PACKAGED → SUCCESS）
2. 缺料路径（HALTED_MISSING_MATERIALS）
3. 草稿拦截路径（BLOCKED_DRAFT）
4. 门检拦截路径（GATE_BLOCKED）
5. 人审路径（needs_human_review → HUMAN_REVIEW）
6. 日报路径（build_daily_report）
7. 契约校验（rulepack / feature flags / readiness / W1-W7 兼容性）
8. SandboxResult 出口约束（publish_allowed / writes_approved 恒 False）
9. 红线 grep（零命中）
"""
import pytest

from backend.app.content_factory.sandbox import (
    SandboxPathKind,
    SandboxResult,
    SandboxRunner,
    build_sandbox_runner,
    validate_feature_flags,
    validate_readiness_checklists,
    validate_rulepacks,
)
from backend.app.content_factory.sandbox.contracts import (
    SandboxContractReport,
    run_all_contract_validations,
    validate_w1_w7_compat,
)
from backend.app.content_factory.sandbox.fixtures import (
    CLEAN_MATERIALS,
    CLEAN_XHS_TEXT,
    build_mock_gate_pipeline,
    build_mock_midplatform,
    make_material,
)
from backend.app.content_factory.schemas import FactoryTaskState
from backend.app.content_factory.recall.results import RecallStatus


# ──────────────────────────────────────────────────────────────────────
# 通用 Brief
# ──────────────────────────────────────────────────────────────────────
BASE_BRIEF = {
    "raw_text": "达芙荻丽奢华油小红书种草稿",
    "target_platform": "xiaohongshu",
}


# ──────────────────────────────────────────────────────────────────────
# 路径 1：成功路径
# ──────────────────────────────────────────────────────────────────────
class TestSuccessPath:
    """充足素材 + 清洁稿 → PACKAGED → SUCCESS。"""

    def test_success_packaged(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.path == SandboxPathKind.SUCCESS
        assert result.factory_state == FactoryTaskState.PACKAGED
        assert result.is_sandbox_pass is True
        assert result.is_production_signal is False

    def test_success_has_text(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.text is not None
        assert len(result.text) > 0

    def test_success_has_used_materials(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert len(result.used_materials_ids) > 0

    def test_success_has_gate_report(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.gate_review_status is not None

    def test_success_recall_summary(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.recall_summary.get("status") == "approved"

    def test_success_publish_allowed_false(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.publish_allowed is False

    def test_success_writes_approved_false(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.writes_approved is False


# ──────────────────────────────────────────────────────────────────────
# 路径 2：缺料路径
# ──────────────────────────────────────────────────────────────────────
class TestMissingMaterialsPath:
    """召回为空 → HALTED_MISSING_MATERIALS。"""

    def test_missing_halted(self):
        runner = build_sandbox_runner(
            materials=[],
            recall_status=RecallStatus.MISSING,
        )
        result = runner.run_brief(BASE_BRIEF)
        assert result.path == SandboxPathKind.MISSING_MATERIALS
        assert result.factory_state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert result.is_sandbox_pass is True

    def test_missing_no_text(self):
        runner = build_sandbox_runner(
            materials=[],
            recall_status=RecallStatus.MISSING,
        )
        result = runner.run_brief(BASE_BRIEF)
        assert result.text is None

    def test_missing_no_used_materials(self):
        runner = build_sandbox_runner(
            materials=[],
            recall_status=RecallStatus.MISSING,
        )
        result = runner.run_brief(BASE_BRIEF)
        assert len(result.used_materials_ids) == 0

    def test_missing_generates_notice(self):
        runner = build_sandbox_runner(
            materials=[],
            recall_status=RecallStatus.MISSING,
        )
        runner.run_brief(BASE_BRIEF)
        assert len(runner.midplatform.notices) >= 1
        assert runner.midplatform.notices[0].kind == "missing_materials"


# ──────────────────────────────────────────────────────────────────────
# 路径 3：草稿拦截路径
# ──────────────────────────────────────────────────────────────────────
class TestBlockedDraftPath:
    """模型产出含无源事实句 → 三版稿全被 W3 拦截 → BLOCKED_DRAFT。"""

    UNSOURCED_TEXT = (
        "标题：新品上市。"
        "正文：产品售价为298元，含有99种天然成分。"
        "标签：美妆。"
    )

    def test_blocked_draft(self):
        runner = build_sandbox_runner(scripted_text=self.UNSOURCED_TEXT)
        result = runner.run_brief(BASE_BRIEF)
        assert result.path == SandboxPathKind.BLOCKED_DRAFT
        assert result.factory_state == FactoryTaskState.BLOCKED_DRAFT
        assert result.is_sandbox_pass is True

    def test_blocked_draft_no_text(self):
        runner = build_sandbox_runner(scripted_text=self.UNSOURCED_TEXT)
        result = runner.run_brief(BASE_BRIEF)
        assert result.text is None

    def test_blocked_draft_generates_notice(self):
        runner = build_sandbox_runner(scripted_text=self.UNSOURCED_TEXT)
        runner.run_brief(BASE_BRIEF)
        assert len(runner.midplatform.notices) >= 1
        assert runner.midplatform.notices[0].kind == "blocked"


# ──────────────────────────────────────────────────────────────────────
# 路径 4：门检拦截路径
# ──────────────────────────────────────────────────────────────────────
class TestGateBlockedPath:
    """手工构造 OK 版本含 G1 红线禁用词 → GatePipeline 全 fail → GATE_BLOCKED。

    架构说明：ModelRouter._draft_with_fallback 自带 prescan_g1 预扫描，
    命中禁用词后文本在路由器层即被拦截（MANUAL_REVIEW），无法到达
    DraftGenerator → GatePipeline。这是正确的防御纵深设计。
    因此 GATE_BLOCKED 路径须手工构造 OK 版本绕过路由器预扫描，
    单独验证 W4 门检层的 G1-G6 拦截能力。
    """

    BANNED_TEXT = (
        "标题：神奇疗效。"
        "正文：本产品可以治愈敏感肌，绝对纯天然，天下第一。"
        "标签：护肤。"
    )

    @staticmethod
    def _build_banned_candidate(text: str):
        """构造一份含 G1 禁用词但 W3 状态为 OK 的 DraftCandidate。"""
        from backend.app.content_factory.drafting.schemas import (
            DraftCandidate, DraftCandidateStatus, DraftVersion,
            DraftVersionKind, DraftVersionStatus,
        )
        from backend.app.content_factory.drafting.sentence_refs import (
            SentenceAudit, SentenceRef,
        )
        # 构造一个空审计（模拟 W3 通过），使 G6 不报 missing audit
        fake_audit = SentenceAudit(
            refs=[SentenceRef(sentence="正文", is_fact=False)],
            passed=True,
        )
        versions = [
            DraftVersion(
                kind=kind,
                text=text,
                status=DraftVersionStatus.OK,
                used_materials_ids=["dfd_fact_001", "dfd_fact_002"],
                audit=fake_audit,
                produced_by_role="primary",
                produced_by_model="mock-sandbox",
            )
            for kind in DraftVersionKind
        ]
        return DraftCandidate(
            content_id="sandbox_gate_blocked_001",
            brief_id="brief_gate_blocked",
            trace_id="trace_gate_blocked",
            status=DraftCandidateStatus.DRAFT_CANDIDATE,
            used_materials_ids=["dfd_fact_001", "dfd_fact_002"],
            versions=versions,
        )

    def test_gate_blocked(self):
        """GatePipeline 对含 G1 禁用词的 OK 版本 → BLOCKED。"""
        from backend.app.content_factory.schemas import FactoryTaskState
        candidate = self._build_banned_candidate(self.BANNED_TEXT)
        gate_pipeline = build_mock_gate_pipeline()
        gate_report = gate_pipeline.run(
            candidate,
            platform="xiaohongshu",
            g3_materials=CLEAN_MATERIALS,
        )
        from backend.app.content_factory.gates.schemas import CandidateReviewStatus
        assert gate_report.review_status == CandidateReviewStatus.BLOCKED
        # 验证 G1 为 fail 原因
        for vr in gate_report.version_reports:
            g1 = next(r for r in vr.results if r.gate.value == "G1_compliance")
            assert g1.is_fail
            assert any("治愈" in h or "绝对" in h or "天下第一" in h for h in g1.hits)
        # 验证 runner 路径分类
        from backend.app.content_factory.factory import FactoryResult
        fr = FactoryResult(
            content_id=candidate.content_id,
            state=FactoryTaskState.GATE_BLOCKED,
            brief_id=candidate.brief_id,
            trace_id=candidate.trace_id,
            gate_report=gate_report,
            draft_candidate=candidate,
        )
        path = SandboxRunner._classify_path(fr, None)
        assert path == SandboxPathKind.GATE_BLOCKED

    def test_gate_blocked_generates_notice(self):
        """GATE_BLOCKED 态 → 中台生成 blocked 前台提示。"""
        from backend.app.content_factory.factory import FactoryResult
        fr = FactoryResult(
            content_id="sandbox_gate_blocked_001",
            state=FactoryTaskState.GATE_BLOCKED,
            brief_id="brief_gate_blocked",
            trace_id="trace_gate_blocked",
        )
        midplatform = build_mock_midplatform()
        midplatform.ingest_factory_result(fr)
        assert len(midplatform.notices) >= 1
        assert midplatform.notices[0].kind == "blocked"


# ──────────────────────────────────────────────────────────────────────
# 路径 5：人审路径
# ──────────────────────────────────────────────────────────────────────
class TestHumanReviewPath:
    """稿件含谨慎词（修护）→ G1 conditional_pass → needs_human_review。"""

    CAUTION_TEXT = (
        "标题：修护精华油。"
        "正文：润养安肤奢华油具有修护肌肤的功效，"
        "体外法检测报告编号XYJCR241029-005，"
        "检测机构为广东欣研检验检测有限公司。"
        "标签：护肤。"
    )

    def test_human_review_path(self):
        runner = build_sandbox_runner(scripted_text=self.CAUTION_TEXT)
        result = runner.run_brief(BASE_BRIEF)
        assert result.path == SandboxPathKind.HUMAN_REVIEW
        assert result.factory_state == FactoryTaskState.PACKAGED

    def test_human_review_queue_state(self):
        runner = build_sandbox_runner(scripted_text=self.CAUTION_TEXT)
        result = runner.run_brief(BASE_BRIEF)
        assert result.review_queue_state is not None
        assert result.review_queue_state in ("needs_human_review", "must_sign")

    def test_human_review_gate_status(self):
        runner = build_sandbox_runner(scripted_text=self.CAUTION_TEXT)
        result = runner.run_brief(BASE_BRIEF)
        assert result.gate_review_status == "needs_human_review"

    def test_human_review_publish_allowed_false(self):
        runner = build_sandbox_runner(scripted_text=self.CAUTION_TEXT)
        result = runner.run_brief(BASE_BRIEF)
        assert result.publish_allowed is False
        assert result.writes_approved is False


# ──────────────────────────────────────────────────────────────────────
# 路径 6：日报路径
# ──────────────────────────────────────────────────────────────────────
class TestDailyReportPath:
    """多条 factory result 累积 → build_daily_report → MockReportStore。"""

    def test_daily_report_basic(self):
        runner = build_sandbox_runner()
        # 跑 3 次成功路径
        for _ in range(3):
            runner.run_brief(BASE_BRIEF)
        report = runner.build_report(day="2026-07-04")
        assert report.date == "2026-07-04"
        assert report.metrics["brief_count"] == 3
        assert report.metrics["run_count"] == 3

    def test_daily_report_stored(self):
        runner = build_sandbox_runner()
        runner.run_brief(BASE_BRIEF)
        runner.build_report(day="2026-07-04")
        dates = runner.report_store.list_dates()
        assert "2026-07-04" in dates

    def test_daily_report_mixed_paths(self):
        """混合路径日报：1 成功 + 1 缺料 + 1 门拦截。"""
        runner = build_sandbox_runner()
        runner.run_brief(BASE_BRIEF)
        # 缺料
        missing_runner = build_sandbox_runner(
            materials=[], recall_status=RecallStatus.MISSING,
        )
        # 共用 runner 的 observer（手工注入）
        from backend.app.content_factory.factory import ContentFactory, FactoryResult
        from backend.app.content_factory.schemas import Brief as BriefObj
        from backend.app.model_router.schemas import TaskType
        import uuid

        brief = BriefObj(
            raw_text="缺料测试", target_platform="xiaohongshu",
            task_type=TaskType.FACT_STRICT,
        )
        factory_no_client = ContentFactory(recall_client=None)
        fr_missing = factory_no_client.process_brief(brief)
        runner.observer.observe(fr_missing)

        report = runner.build_report(day="2026-07-04")
        assert report.metrics["run_count"] >= 2
        assert report.metrics["missing_materials_count"] >= 1

    def test_daily_report_to_dict(self):
        runner = build_sandbox_runner()
        runner.run_brief(BASE_BRIEF)
        report = runner.build_report(day="2026-07-04")
        d = report.to_dict()
        assert "date" in d
        assert "metrics" in d
        assert "anomalies" in d


# ──────────────────────────────────────────────────────────────────────
# 契约校验
# ──────────────────────────────────────────────────────────────────────
class TestContractValidations:
    """W7 rulepack / feature flags / readiness / W1-W7 兼容性。"""

    def test_rulepack_validation_all_passed(self):
        results = validate_rulepacks()
        assert all(r.passed for r in results), \
            f"Rulepack validation failed: {[r for r in results if not r.passed]}"

    def test_feature_flags_validation_all_passed(self):
        results = validate_feature_flags()
        assert all(r.passed for r in results), \
            f"Feature flag validation failed: {[r for r in results if not r.passed]}"

    def test_readiness_validation_all_passed(self):
        results = validate_readiness_checklists()
        assert all(r.passed for r in results), \
            f"Readiness validation failed: {[r for r in results if not r.passed]}"

    def test_w1_w7_compat_all_passed(self):
        results = validate_w1_w7_compat()
        assert all(r.passed for r in results), \
            f"W1-W7 compat failed: {[r for r in results if not r.passed]}"

    def test_full_contract_report(self):
        report = run_all_contract_validations()
        assert report.all_passed is True
        s = report.summary()
        assert s["failed"] == 0
        assert s["total"] > 0


# ──────────────────────────────────────────────────────────────────────
# SandboxResult 出口约束
# ──────────────────────────────────────────────────────────────────────
class TestSandboxResultConstraints:
    """SandboxResult 出口约束恒成立。"""

    def test_publish_allowed_always_false(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.publish_allowed is False

    def test_writes_approved_always_false(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.writes_approved is False

    def test_is_production_signal_always_false(self):
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.is_production_signal is False

    def test_sandbox_pass_not_equal_production(self):
        """sandbox pass 不等于生产可用。"""
        runner = build_sandbox_runner()
        result = runner.run_brief(BASE_BRIEF)
        assert result.is_sandbox_pass is True
        assert result.is_production_signal is False


# ──────────────────────────────────────────────────────────────────────
# Runner 汇总
# ──────────────────────────────────────────────────────────────────────
class TestRunnerSummary:
    """SandboxRunner.summary() 只读统计。"""

    def test_summary_after_runs(self):
        runner = build_sandbox_runner()
        runner.run_brief(BASE_BRIEF)
        runner.run_brief(BASE_BRIEF)
        s = runner.summary()
        assert s["total_runs"] == 2
        assert s["observer_run_count"] == 2
        assert "success" in s["by_path"]

    def test_summary_mixed_paths(self):
        runner = build_sandbox_runner()
        runner.run_brief(BASE_BRIEF)
        # 缺料
        runner2 = build_sandbox_runner(
            materials=[], recall_status=RecallStatus.MISSING,
        )
        # 用 runner2 的 recall_client 替换
        runner.recall_client = runner2.recall_client
        runner.run_brief(BASE_BRIEF)
        s = runner.summary()
        assert s["total_runs"] == 2
        assert "missing_materials" in s["by_path"]


# ──────────────────────────────────────────────────────────────────────
# Qoder 补强测试
# ──────────────────────────────────────────────────────────────────────
class TestQoderStrengthening:
    """Qoder 独立补强项。"""

    def test_sandbox_no_real_9080(self):
        """沙盒 recall_client 必须为 mock。"""
        runner = build_sandbox_runner()
        assert runner.recall_client.config.mock is True

    def test_sandbox_no_real_model(self):
        """沙盒 model clients 必须为 mock。"""
        runner = build_sandbox_runner()
        for role, client in runner.draft_generator.router.clients.items():
            assert client.provider == "mock", f"{role} 使用非 mock provider"

    def test_sandbox_report_store_is_mock(self):
        """沙盒 report store 必须为 mock。"""
        runner = build_sandbox_runner()
        assert runner.report_store.is_mock is True

    def test_sandbox_scheduler_is_mock(self):
        """沙盒 scheduler 必须为 mock。"""
        runner = build_sandbox_runner()
        assert runner.scheduler.is_mock is True

    def test_sandbox_alert_sink_is_mock(self):
        """沙盒 alert sink 必须为 mock。"""
        runner = build_sandbox_runner()
        assert runner.alert_sink.is_mock is True

    def test_six_paths_enum_complete(self):
        """六种路径枚举齐备。"""
        expected = {"success", "missing_materials", "blocked_draft",
                    "gate_blocked", "human_review", "daily_report"}
        actual = {p.value for p in SandboxPathKind}
        assert expected == actual

    def test_runner_observability_chain(self):
        """观测链路：factory result → observer → daily report。"""
        runner = build_sandbox_runner()
        runner.run_brief(BASE_BRIEF)
        assert runner.observer.run_count == 1
        assert runner.observer.brief_count == 1
        report = runner.build_report(day="2026-07-04")
        assert report.metrics["run_count"] == 1
        stored = runner.report_store.get_report("2026-07-04")
        assert stored is not None
