"""W5 测试 — 审读包与内容经营中台联动骨架。

覆盖 M1-W5 条件施工许可 五·必测项 1-17：
- ReviewPackagePre 进入 candidate_review
- 三版稿/六门 gate_summary 展示
- blocked 版本不可备发；needs_human_review/must_sign 提示
- ready_for_review 可备发；marked_ready_to_publish ≠ 发布/approved
- rejected_for_revision 不进发布；candidate_review 不写库
- 缺料停单前台提示；G1/G3 fail 高亮
- conditional_pass 进人审不自动发布
- publish_allowed / writes_approved 恒 False
"""
import pytest

from backend.app.content_factory import Brief, ContentFactory, FactoryTaskState
from backend.app.content_factory.drafting import (
    DraftCandidate, DraftCandidateStatus, DraftGenerator, DraftVersion,
    DraftVersionKind, DraftVersionStatus, audit_sentences,
)
from backend.app.content_factory.gates import GatePipeline, build_review_package_pre
from backend.app.content_factory.gates.review_package import ReviewPackagePre
from backend.app.content_factory.midplatform import (
    CandidateReviewQueue, CandidateReviewState, InvalidReviewAction,
    MidPlatformMock, ReviewPackageDetail, build_review_package_detail,
)
from backend.app.content_factory.midplatform.pages import FrontdeskNotice
from backend.app.content_factory.recall import MockRecallClient, RecallResult, RecallStatus
from backend.app.model_router import (
    MockModelClient, ModelReply, ModelRole, ModelRouter, ModelRouterConfig,
)


# ──────────────────────────────────────────────────────────────────────
# 构造工具
# ──────────────────────────────────────────────────────────────────────
def mat(id, content):
    return {"id": id, "content": content, "material_type": "fact_card",
            "source_type": "9080_approved", "status": "active"}


CLEAN_XHS = ("标题：奢华油的日常。正文：润养安肤奢华油为普通化妆品，"
             "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司。标签：护肤。")
CLEAN_MATERIALS = [
    mat("dfd_fact_001", "润养安肤奢华油为普通化妆品"),
    mat("dfd_fact_002", "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司"),
]


def make_candidate(text=CLEAN_XHS, materials=CLEAN_MATERIALS):
    versions = [DraftVersion(kind=k, text=text, status=DraftVersionStatus.OK,
                             used_materials_ids=[m["id"] for m in materials],
                             audit=audit_sentences(text, materials)) for k in DraftVersionKind]
    return DraftCandidate(content_id="content_w5", brief_id="brief_w5", trace_id="trace_w5",
                          status=DraftCandidateStatus.DRAFT_CANDIDATE,
                          used_materials_ids=[m["id"] for m in materials], versions=versions)


def make_pre(text=CLEAN_XHS, platform="xiaohongshu"):
    cand = make_candidate(text)
    report = GatePipeline().run(cand, platform=platform, g3_materials=CLEAN_MATERIALS)
    return build_review_package_pre(cand, report), cand, report


def make_factory(reply_text, materials, with_pipeline=True):
    cfg = ModelRouterConfig.default()
    cl = {r: MockModelClient(model_name=f"m-{r.value}", scripted_replies=[ModelReply(text=reply_text)])
          for r in ModelRole}
    router = ModelRouter(config=cfg, clients=cl)
    client = MockRecallClient(scripted_results=[RecallResult(materials=list(materials), status=RecallStatus.APPROVED)])
    return ContentFactory(recall_client=client, draft_generator=DraftGenerator(router=router),
                          gate_pipeline=GatePipeline() if with_pipeline else None)


# ──────────────────────────────────────────────────────────────────────
# 必测 1/2/3：入队 + 三版稿 + 六门展示
# ──────────────────────────────────────────────────────────────────────
class TestEnqueueAndDisplay:
    def test_review_package_pre_enters_candidate_review(self):
        pre, _, _ = make_pre()
        q = CandidateReviewQueue()
        entry = q.enqueue(pre)
        assert q.count() == 1
        assert entry.state == CandidateReviewState.READY_FOR_REVIEW

    def test_three_versions_in_detail(self):
        pre, _, _ = make_pre()
        detail = build_review_package_detail(pre)
        assert len(detail.version_views) == 3

    def test_six_gate_summary_complete(self):
        pre, _, _ = make_pre()
        detail = build_review_package_detail(pre)
        for vv in detail.version_views:
            assert len(vv.gate_rows) == 6
            gates = {r.gate for r in vv.gate_rows}
            assert gates == {"G1_compliance", "G2_state_boundary", "G3_fact_ref",
                             "G4_platform_structure", "G5_brand_consistency", "G6_format_complete"}


# ──────────────────────────────────────────────────────────────────────
# 必测 4/13：blocked 不可备发；G1/G3 fail 高亮
# ──────────────────────────────────────────────────────────────────────
class TestBlockedAndHighlight:
    def test_blocked_version_cannot_mark_ready(self):
        # 串品牌 → G5 fail → 候选 blocked
        pre, _, _ = make_pre(text="标题：油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。")
        q = CandidateReviewQueue()
        entry = q.enqueue(pre)
        assert entry.state == CandidateReviewState.BLOCKED
        assert all(not vv.can_mark_ready for vv in entry.detail.version_views)

    def test_blocked_cannot_transition_to_marked_ready(self):
        pre, _, _ = make_pre(text="标题：油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。")
        mp = MidPlatformMock()
        entry = mp.queue.enqueue(pre)
        with pytest.raises(InvalidReviewAction):
            mp.action_mark_ready(entry.content_id, operator="小编")

    def test_g1_fail_highlighted(self):
        # 直接构造一版含 G1 fail 的 pre：借 review_package 的 gate_summary
        # 用一个 G3 无源事实句稿 → G3 fail 高亮
        pre, _, _ = make_pre(text="标题。正文临床数据显示99分。标签。")
        detail = build_review_package_detail(pre)
        highlighted = [r for vv in detail.version_views for r in vv.gate_rows if r.highlight]
        assert highlighted  # G3 fail 被高亮
        assert all(r.gate in ("G1_compliance", "G3_fact_ref") for r in highlighted)


# ──────────────────────────────────────────────────────────────────────
# 必测 5/6/14：needs_human_review / must_sign / conditional
# ──────────────────────────────────────────────────────────────────────
class TestHumanReviewPaths:
    def test_conditional_needs_human_review_notice(self):
        # 谨慎词"修护"→ conditional → needs_human_review
        text = CLEAN_XHS.replace("为普通化妆品", "为普通化妆品，有助于修护肌肤状态")
        pre, _, _ = make_pre(text=text)
        entry = CandidateReviewQueue().enqueue(pre)
        assert entry.state == CandidateReviewState.NEEDS_HUMAN_REVIEW
        assert entry.must_sign is True
        assert "人工审读" in entry.detail.frontdesk_notice

    def test_needs_human_cannot_directly_mark_ready(self):
        text = CLEAN_XHS.replace("为普通化妆品", "为普通化妆品，有助于修护肌肤状态")
        pre, _, _ = make_pre(text=text)
        mp = MidPlatformMock()
        entry = mp.queue.enqueue(pre)
        # 必测 14：conditional 不可自动/直接备发，必须先提交签发
        with pytest.raises(InvalidReviewAction):
            mp.action_mark_ready(entry.content_id, operator="小编")

    def test_submit_signoff_then_mark_ready(self):
        text = CLEAN_XHS.replace("为普通化妆品", "为普通化妆品，有助于修护肌肤状态")
        pre, _, _ = make_pre(text=text)
        mp = MidPlatformMock()
        entry = mp.queue.enqueue(pre)
        mp.action_submit_signoff(entry.content_id, operator="小编")     # → must_sign
        assert entry.state == CandidateReviewState.MUST_SIGN
        mp.action_mark_ready(entry.content_id, operator="吴哥")          # 签发后备发
        assert entry.state == CandidateReviewState.MARKED_READY_TO_PUBLISH


# ──────────────────────────────────────────────────────────────────────
# 必测 7/8/9/10：备发 ≠ 发布/approved；驳回不进发布
# ──────────────────────────────────────────────────────────────────────
class TestMarkReadySemantics:
    def test_ready_can_be_marked(self):
        pre, _, _ = make_pre()
        mp = MidPlatformMock()
        entry = mp.queue.enqueue(pre)
        st = mp.action_mark_ready(entry.content_id, operator="小编")
        assert st == CandidateReviewState.MARKED_READY_TO_PUBLISH

    def test_marked_ready_is_not_publish_not_approved(self):
        pre, _, _ = make_pre()
        mp = MidPlatformMock()
        entry = mp.queue.enqueue(pre)
        mp.action_mark_ready(entry.content_id, operator="小编")
        # 备发只是状态标记：无 publish_allowed、无 approved 写入、detail 出口常量仍 False
        assert entry.detail.publish_allowed is False
        assert entry.detail.writes_approved is False
        # 动作留痕明确标注"≠发布/≠approved"
        assert any("≠发布" in a["note"] for a in entry.action_log)

    def test_rejected_is_terminal_not_publish(self):
        pre, _, _ = make_pre()
        mp = MidPlatformMock()
        entry = mp.queue.enqueue(pre)
        mp.action_reject(entry.content_id, operator="小编", reason="口径不符")
        assert entry.state == CandidateReviewState.REJECTED_FOR_REVISION
        # 驳回后不可再备发
        with pytest.raises(InvalidReviewAction):
            mp.action_mark_ready(entry.content_id, operator="小编")


# ──────────────────────────────────────────────────────────────────────
# 必测 11：candidate_review 不写正式库（内存 only）
# ──────────────────────────────────────────────────────────────────────
class TestNoPersistence:
    def test_queue_is_memory_only(self):
        pre, _, _ = make_pre()
        q1, q2 = CandidateReviewQueue(), CandidateReviewQueue()
        q1.enqueue(pre)
        assert q1.count() == 1 and q2.count() == 0  # 各自内存，无共享持久层


# ──────────────────────────────────────────────────────────────────────
# 必测 12/13：中台三页一弹窗 + 缺料/门拦截前台提示
# ──────────────────────────────────────────────────────────────────────
class TestMidPlatformPages:
    def test_three_pages_and_modal(self):
        pre, cand, report = make_pre()
        mp = MidPlatformMock()
        mp.queue.enqueue(pre)
        assert mp.brief_order_page({"raw_text": "x", "target_platform": "xiaohongshu"})["accepted"]
        desk = mp.review_desk_page()
        assert desk["page"] == "review_desk" and len(desk["items"]) == 1
        modal = mp.open_detail_modal(pre.content_id)
        assert isinstance(modal, ReviewPackageDetail)
        assert mp.daily_report_page()["queue_total"] == 1

    def test_missing_materials_frontdesk_notice(self):
        # 缺料停单 → 中台前台提示（必测 12）
        f = make_factory(CLEAN_XHS, [])   # 空素材 → HALTED
        r = f.process_brief(Brief(raw_text="x", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        mp = MidPlatformMock()
        notice = mp.ingest_factory_result(r)
        assert isinstance(notice, FrontdeskNotice) and notice.kind == "missing_materials"
        assert mp.queue.count() == 0  # 缺料不入审读队列

    def test_gate_blocked_frontdesk_notice(self):
        # 串品牌 → GATE_BLOCKED → blocked 前台提示（必测 13）
        f = make_factory("标题：油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。", CLEAN_MATERIALS)
        r = f.process_brief(Brief(raw_text="x", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.GATE_BLOCKED
        mp = MidPlatformMock()
        notice = mp.ingest_factory_result(r)
        assert isinstance(notice, FrontdeskNotice) and notice.kind == "blocked"

    def test_packaged_result_enqueues(self):
        f = make_factory(CLEAN_XHS, CLEAN_MATERIALS)
        r = f.process_brief(Brief(raw_text="x", target_platform="xiaohongshu"))
        assert r.state == FactoryTaskState.PACKAGED
        mp = MidPlatformMock()
        entry = mp.ingest_factory_result(r)
        assert entry.state == CandidateReviewState.READY_FOR_REVIEW
        assert mp.queue.count() == 1


# ──────────────────────────────────────────────────────────────────────
# 必测 15/16：publish_allowed / writes_approved 恒 False，无写入口
# ──────────────────────────────────────────────────────────────────────
class TestNoPublishNoApproved:
    def test_detail_constants_false(self):
        pre, _, _ = make_pre()
        detail = build_review_package_detail(pre)
        assert detail.publish_allowed is False
        assert detail.writes_approved is False

    def test_no_write_entry(self):
        with pytest.raises(TypeError):
            ReviewPackageDetail(content_id="c", brief_id="b", trace_id="t",
                                review_state=CandidateReviewState.READY_FOR_REVIEW,
                                must_sign=False, loop_rounds_used=1, publish_allowed=True)
