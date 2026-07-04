"""W4 测试 — 六硬门编排与候选裁决层骨架。

覆盖 M1-W4 条件施工许可 五·必测项 1-16：
- 三版稿逐版过 G1-G6
- G1 红线 fail → 版本 blocked
- G2 状态越界 → fail
- 无 source_ref 事实句 → G3 fail；检测缺要素 → G3 fail
- G4 只判结构，非结构问题路由不裁决
- 串品牌/串产品 → G5 fail
- 审读包字段缺失 → G6 fail
- conditional_pass 只进人审、不自动发布
- loop ≤3 圈；3 圈仍 fail → blocked
- 有 warning 无 fail → ready_for_review
- conditional_pass → needs_human_review/must_sign
- publish_allowed / writes_approved 恒 False
"""
import pytest

from backend.app.content_factory import Brief, ContentFactory, FactoryTaskState
from backend.app.content_factory.drafting import (
    DraftCandidate,
    DraftCandidateStatus,
    DraftGenerator,
    DraftVersion,
    DraftVersionKind,
    DraftVersionStatus,
    audit_sentences,
)
from backend.app.content_factory.gates import (
    CandidateGateReport,
    CandidateReviewStatus,
    GatePipeline,
    GateContext,
    GateName,
    GateVerdict,
    MockG3Adjudicator,
    VersionLoopStatus,
    build_review_package_pre,
    gate_g1,
    gate_g2,
    gate_g4,
    gate_g5,
    gate_g6,
)
from backend.app.content_factory.recall import MockRecallClient, RecallResult, RecallStatus
from backend.app.model_router import (
    MockModelClient,
    ModelReply,
    ModelRole,
    ModelRouter,
    ModelRouterConfig,
)


# ──────────────────────────────────────────────────────────────────────
# 构造工具
# ──────────────────────────────────────────────────────────────────────
def mat(id, content):
    return {"id": id, "content": content, "material_type": "fact_card",
            "source_type": "9080_approved", "status": "active"}


# 一份"过 G1-G6 全清"的合规稿：含标题/正文/标签(小红书结构)、检测三要素、只提本品
CLEAN_XHS = (
    "标题：奢华油的日常。"
    "正文：润养安肤奢华油为普通化妆品，体外法检测报告编号XYJCR241029-005，"
    "检测机构为广东欣研检验检测有限公司。"
    "标签：护肤。"
)
CLEAN_MATERIALS = [
    mat("dfd_fact_001", "润养安肤奢华油为普通化妆品"),
    mat("dfd_fact_002", "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司"),
]


def make_version(kind, text, materials=CLEAN_MATERIALS, status=DraftVersionStatus.OK):
    ids = [m["id"] for m in materials]
    return DraftVersion(
        kind=kind, text=text, status=status,
        used_materials_ids=ids,
        audit=audit_sentences(text, materials),
    )


def make_candidate(text=CLEAN_XHS, materials=CLEAN_MATERIALS):
    versions = [make_version(k, text, materials) for k in DraftVersionKind]
    return DraftCandidate(
        content_id="content_w4", brief_id="brief_w4", trace_id="trace_w4",
        status=DraftCandidateStatus.DRAFT_CANDIDATE,
        used_materials_ids=[m["id"] for m in materials],
        versions=versions,
    )


def ctx(text, platform="xiaohongshu", ids=("dfd_fact_001",), audit=True):
    return GateContext(version_kind="professional", text=text, platform=platform,
                       used_materials_ids=list(ids), has_audit=audit)


# ──────────────────────────────────────────────────────────────────────
# 必测 1：三版稿逐版过 G1-G6
# ──────────────────────────────────────────────────────────────────────
class TestPipelineRunsAllVersions:
    def test_all_three_versions_reported(self):
        report = GatePipeline().run(make_candidate(), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        assert len(report.version_reports) == 3
        for vr in report.version_reports:
            assert len(vr.results) == 6  # G1-G6 各一

    def test_clean_candidate_ready_for_review(self):
        report = GatePipeline().run(make_candidate(), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.READY_FOR_REVIEW


# ──────────────────────────────────────────────────────────────────────
# 必测 2：G1 红线 fail → 版本 blocked
# ──────────────────────────────────────────────────────────────────────
class TestG1Redline:
    def test_g1_banned_word_fails(self):
        r = gate_g1(ctx("本品可根治敏感肌"))
        assert r.verdict == GateVerdict.FAIL
        assert "根治" in r.hits

    def test_g1_redline_blocks_version_immediately(self):
        # 三版都含红线词 → 无重试、直接 blocked，候选 BLOCKED
        cand = make_candidate(text="标题。正文根治敏感肌。标签。")
        report = GatePipeline().run(cand, platform="xiaohongshu", g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.BLOCKED
        for vr in report.version_reports:
            assert vr.loop_status == VersionLoopStatus.BLOCKED
            assert vr.loop_rounds == 1  # G1 红线不重试

    def test_g1_caution_word_conditional(self):
        r = gate_g1(ctx("有助于修护肌肤状态"))
        assert r.verdict == GateVerdict.CONDITIONAL_PASS


# ──────────────────────────────────────────────────────────────────────
# 必测 3：G2 状态越界 → fail
# ──────────────────────────────────────────────────────────────────────
class TestG2StateBoundary:
    @pytest.mark.parametrize("bad", ["用了就转运", "改变命运", "旺财好物", "能量场调理"])
    def test_g2_overreach_fails(self, bad):
        assert gate_g2(ctx(bad)).verdict == GateVerdict.FAIL

    def test_g2_state_language_passes(self):
        assert gate_g2(ctx("老客势能还在，只是没被接住")).verdict == GateVerdict.PASS


# ──────────────────────────────────────────────────────────────────────
# 必测 4/5：G3 事实引用门
# ──────────────────────────────────────────────────────────────────────
class TestG3FactRef:
    def test_unsourced_fact_sentence_fails(self):
        adj = MockG3Adjudicator()
        r = adj.adjudicate("临床数据显示99分有效。", CLEAN_MATERIALS)
        assert r.verdict == GateVerdict.FAIL

    def test_detection_missing_elements_fails(self):
        # 有"检测"宣称但缺机构 → fail
        adj = MockG3Adjudicator()
        mats = [mat("m", "体外法检测报告编号XYJCR241029-005")]
        r = adj.adjudicate("体外法检测报告编号XYJCR241029-005。", mats)
        assert r.verdict == GateVerdict.FAIL
        assert any("机构" in h for h in r.hits)

    def test_detection_complete_passes(self):
        adj = MockG3Adjudicator()
        r = adj.adjudicate(
            "润养安肤奢华油为普通化妆品，体外法检测报告编号XYJCR241029-005，"
            "检测机构为广东欣研检验检测有限公司。", CLEAN_MATERIALS)
        assert r.verdict == GateVerdict.PASS

    def test_g3_uses_injectable_adjudicator_not_hardwired(self):
        """G3 走可注入的正式裁决接口（不把 W3 启发式写死）。"""
        class AlwaysFail:
            def adjudicate(self, text, materials):
                from backend.app.content_factory.gates.schemas import GateResult
                return GateResult(GateName.G3_FACT_REF, GateVerdict.FAIL, note="injected")
        report = GatePipeline(fact_adjudicator=AlwaysFail()).run(
            make_candidate(), platform="xiaohongshu", g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.BLOCKED


# ──────────────────────────────────────────────────────────────────────
# 必测 6：G4 只判结构，非结构问题路由不裁决
# ──────────────────────────────────────────────────────────────────────
class TestG4StructureOnly:
    def test_g4_missing_required_structure_fails(self):
        # 小红书缺"标签" → 结构 fail
        r = gate_g4(ctx("标题。正文。", platform="xiaohongshu"))
        assert r.verdict == GateVerdict.FAIL
        assert "标签" in r.hits

    def test_g4_does_not_adjudicate_compliance_only_routes(self):
        # 含红线词但结构齐全 → G4 不 fail，只路由到 G1
        text = "标题。正文根治敏感肌。标签。"
        r = gate_g4(ctx(text, platform="xiaohongshu"))
        assert r.verdict != GateVerdict.FAIL           # G4 不裁决合规
        assert GateName.G1_COMPLIANCE in r.routed_to    # 只路由

    def test_g4_routes_brand_and_state_issues(self):
        text = "标题。正文提到雅诗兰黛还说转运。标签。"
        r = gate_g4(ctx(text, platform="xiaohongshu"))
        assert GateName.G5_BRAND_CONSISTENCY in r.routed_to
        assert GateName.G2_STATE_BOUNDARY in r.routed_to

    def test_g4_optional_missing_is_warning(self):
        # brand_site 必需齐全、缺可选 FAQ/SEO摘要 → warning
        r = gate_g4(ctx("标题正文齐全的正文内容", platform="brand_site"))
        assert r.verdict == GateVerdict.WARNING


# ──────────────────────────────────────────────────────────────────────
# 必测 7：串品牌/串产品 → G5 fail
# ──────────────────────────────────────────────────────────────────────
class TestG5BrandConsistency:
    def test_other_brand_fails(self):
        assert gate_g5(ctx("对比雅诗兰黛更好")).verdict == GateVerdict.FAIL

    def test_other_product_fails(self):
        assert gate_g5(ctx("我们的面膜也不错")).verdict == GateVerdict.FAIL

    def test_only_dfd_passes(self):
        assert gate_g5(ctx("润养安肤奢华油很适合日常")).verdict == GateVerdict.PASS


# ──────────────────────────────────────────────────────────────────────
# 必测 8：审读包字段缺失 → G6 fail
# ──────────────────────────────────────────────────────────────────────
class TestG6FormatComplete:
    def test_empty_text_fails(self):
        assert gate_g6(ctx("", ids=("m1",))).verdict == GateVerdict.FAIL

    def test_missing_used_materials_ids_fails(self):
        assert gate_g6(ctx("正文", ids=())).verdict == GateVerdict.FAIL

    def test_missing_audit_fails(self):
        assert gate_g6(ctx("正文", ids=("m1",), audit=False)).verdict == GateVerdict.FAIL

    def test_complete_passes(self):
        assert gate_g6(ctx("正文", ids=("m1",), audit=True)).verdict == GateVerdict.PASS


# ──────────────────────────────────────────────────────────────────────
# 必测 9/13：conditional_pass → 人审 + must_sign，不自动发布
# ──────────────────────────────────────────────────────────────────────
class TestConditionalPass:
    def test_conditional_needs_human_review_must_sign(self):
        # 含谨慎词"修护"→ G1 conditional_pass；其余门过
        text = "标题：奢华油。正文：润养安肤奢华油为普通化妆品，有助于修护肌肤状态。标签：护肤。"
        report = GatePipeline().run(make_candidate(text=text), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.NEEDS_HUMAN_REVIEW
        assert report.must_sign is True
        assert report.publish_allowed is False   # 不自动发布


# ──────────────────────────────────────────────────────────────────────
# 必测 10/11：loop ≤3 圈；3 圈仍 fail → blocked
# ──────────────────────────────────────────────────────────────────────
class TestLoop:
    def test_no_callback_single_round_blocked(self):
        # 缺结构 fail（无 标题/标签 标记）、无 revise 回调 → 1 圈定 blocked
        body = ("润养安肤奢华油为普通化妆品，体外法检测报告编号XYJCR241029-005，"
                "检测机构为广东欣研检验检测有限公司。")
        cand = make_candidate(text=body)
        report = GatePipeline().run(cand, platform="xiaohongshu", g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.BLOCKED
        assert report.loop_result.rounds_used == 1

    def test_loop_caps_at_3_rounds(self):
        # revise 回调永不修好 → 恰好 3 圈后 blocked
        calls = {"n": 0}
        def never_fix(version, report):
            calls["n"] += 1
            return version  # 不改，继续 fail
        cand = make_candidate(text="标题。正文。")  # 缺"标签"→ G4 fail（非红线，可 loop）
        report = GatePipeline(revise_callback=never_fix).run(
            cand, platform="xiaohongshu", g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.BLOCKED
        assert report.loop_result.rounds_used == 3
        # 每版重生成 2 次（圈2、圈3）×3 版
        assert calls["n"] == 6

    def test_loop_converges_when_revised(self):
        # revise 回调在第 2 圈补上"标签" → 收敛为 ready
        def fix(version, report):
            version.text = (version.text or "") + "标签：护肤。"
            version.audit = audit_sentences(version.text, CLEAN_MATERIALS)
            return version
        base = ("标题：奢华油。正文：润养安肤奢华油为普通化妆品，"
                "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司。")
        cand = make_candidate(text=base)  # 缺标签
        report = GatePipeline(revise_callback=fix).run(
            cand, platform="xiaohongshu", g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.READY_FOR_REVIEW
        assert report.loop_result.rounds_used == 2


# ──────────────────────────────────────────────────────────────────────
# 必测 12：warning 无 fail → ready_for_review
# ──────────────────────────────────────────────────────────────────────
class TestWarningReady:
    def test_warning_only_is_ready(self):
        # brand_site 必需齐、缺可选 → 仅 warning
        text = ("标题：奢华油资产稿。正文：润养安肤奢华油为普通化妆品，"
                "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司。")
        report = GatePipeline().run(make_candidate(text=text), platform="brand_site",
                                    g3_materials=CLEAN_MATERIALS)
        assert report.review_status == CandidateReviewStatus.READY_FOR_REVIEW
        # 确有 warning
        assert any(vr.warnings for vr in report.version_reports)


# ──────────────────────────────────────────────────────────────────────
# 必测 14/15：publish_allowed / writes_approved 恒 False，无写入口
# ──────────────────────────────────────────────────────────────────────
class TestNoPublishNoApproved:
    def test_report_constants_false(self):
        report = GatePipeline().run(make_candidate(), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        assert report.publish_allowed is False
        assert report.writes_approved is False

    def test_no_write_entry(self):
        with pytest.raises(TypeError):
            CandidateGateReport(content_id="c", brief_id="b", trace_id="t",
                                review_status=CandidateReviewStatus.READY_FOR_REVIEW,
                                publish_allowed=True)

    def test_review_package_pre_constants_false(self):
        report = GatePipeline().run(make_candidate(), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        pkg = build_review_package_pre(make_candidate(), report)
        assert pkg.publish_allowed is False
        assert pkg.writes_approved is False


# ──────────────────────────────────────────────────────────────────────
# 端到端：factory 接入 gate_pipeline
# ──────────────────────────────────────────────────────────────────────
def make_factory(reply_text, materials, pipeline=None):
    cfg = ModelRouterConfig.default()
    cl = {r: MockModelClient(model_name=f"mock-{r.value}",
                             scripted_replies=[ModelReply(text=reply_text)]) for r in ModelRole}
    router = ModelRouter(config=cfg, clients=cl)
    client = MockRecallClient(scripted_results=[
        RecallResult(materials=list(materials), status=RecallStatus.APPROVED)])
    return ContentFactory(recall_client=client,
                          draft_generator=DraftGenerator(router=router),
                          gate_pipeline=pipeline or GatePipeline())


class TestFactoryE2E:
    def test_clean_e2e_packaged_with_gate_report(self):
        f = make_factory(CLEAN_XHS, CLEAN_MATERIALS)
        r = f.process_brief(Brief(raw_text="奢华油科普", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.PACKAGED
        assert r.gate_report is not None
        assert r.gate_report.review_status == CandidateReviewStatus.READY_FOR_REVIEW

    def test_gate_blocked_e2e_brand_cross(self):
        # 串品牌"雅诗兰黛"不在 W0.5 router 禁用词内 → W3 出 OK 稿 →
        # W4 G5 全版 fail → 候选 BLOCKED → factory GATE_BLOCKED（验证 W4 拦截层真实生效）
        text = ("标题：奢华油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。")
        f = make_factory(text, CLEAN_MATERIALS)
        r = f.process_brief(Brief(raw_text="奢华油科普", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.GATE_BLOCKED
        assert r.gate_report.review_status == CandidateReviewStatus.BLOCKED
        assert f.staging.count() == 0   # 门拦截不写 staging

    def test_no_pipeline_keeps_w3_behavior(self):
        cfg = ModelRouterConfig.default()
        cl = {r: MockModelClient(model_name=f"mock-{r.value}",
                                 scripted_replies=[ModelReply(text=CLEAN_XHS)]) for r in ModelRole}
        client = MockRecallClient(scripted_results=[
            RecallResult(materials=list(CLEAN_MATERIALS), status=RecallStatus.APPROVED)])
        f = ContentFactory(recall_client=client,
                           draft_generator=DraftGenerator(router=ModelRouter(config=cfg, clients=cl)))
        r = f.process_brief(Brief(raw_text="奢华油科普", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.PACKAGED
        assert r.gate_report is None  # 未注入 pipeline


# ──────────────────────────────────────────────────────────────────────
# Qoder 补强测试
# ──────────────────────────────────────────────────────────────────────


class TestGateBlockedTerminal:
    """GATE_BLOCKED 是终态，不可再转换。"""

    def test_gate_blocked_is_terminal(self):
        from backend.app.content_factory.task_state import StateMachine, InvalidTransition
        sm = StateMachine()
        sm.transition(FactoryTaskState.PRODUCING, operator="factory")
        sm.transition(FactoryTaskState.GATED, operator="factory")
        sm.transition(FactoryTaskState.GATE_BLOCKED, operator="factory")
        assert sm.is_terminal
        with pytest.raises(InvalidTransition):
            sm.transition(FactoryTaskState.PACKAGED, operator="factory")


class TestReviewPackageSlots:
    """审读包前置结构的槽位与版本一一对应。"""

    def test_review_package_has_3_slots(self):
        report = GatePipeline().run(make_candidate(), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        pkg = build_review_package_pre(make_candidate(), report)
        assert len(pkg.version_slots) == 3
        kinds = {s.version_kind for s in pkg.version_slots}
        assert kinds == {"professional", "state_aesthetic", "platform_rewrite"}

    def test_review_package_slot_gate_summary(self):
        report = GatePipeline().run(make_candidate(), platform="xiaohongshu",
                                    g3_materials=CLEAN_MATERIALS)
        pkg = build_review_package_pre(make_candidate(), report)
        for slot in pkg.version_slots:
            # 每版槽位应有 6 门摘要
            assert len(slot.gate_summary) == 6
            assert slot.is_reviewable is True


class TestFactoryE2ENeedsHumanReview:
    """factory E2E：conditional_pass → NEEDS_HUMAN_REVIEW + must_sign + PACKAGED。"""

    def test_conditional_e2e_packaged_with_must_sign(self):
        # 含谨慎词“修护” → G1 conditional_pass → NEEDS_HUMAN_REVIEW
        text = ("标题：奢华油。正文：润养安肤奢华油为普通化妆品，有助于修护肌肤状态，"
                "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司。标签：护肤。")
        f = make_factory(text, CLEAN_MATERIALS)
        r = f.process_brief(Brief(raw_text="奢华油科普", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.PACKAGED
        assert r.gate_report is not None
        assert r.gate_report.review_status == CandidateReviewStatus.NEEDS_HUMAN_REVIEW
        assert r.gate_report.must_sign is True
        # conditional_pass 不自动发布
        assert r.gate_report.publish_allowed is False
        # staging 应有写入（PACKAGED 正常路径）
        assert f.staging.count() == 1
