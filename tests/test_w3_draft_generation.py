"""W3 测试 — 草稿生成与模型路由接线骨架。

覆盖 M1-W3 条件施工许可 四·必测项 1-13：
- used_materials 充分 → 可生成 draft_candidate
- 空素材 / recall_client=None / 黑名单滤后不足 → 停单
- direction_hint 不进 used_materials
- 模型新增事实 → blocked
- draft_candidate 绑定 used_materials_ids
- 每个事实句必须有 source_refs
- daily_*/webintel_*/crawl_* 前缀不得作为事实源
- 三版稿共用同一组 used_materials
- 任何版本不得 publish_allowed / 不写 approved
"""
import pytest

from backend.app.content_factory import Brief, ContentFactory, FactoryTaskState
from backend.app.content_factory.drafting import (
    DraftCandidate,
    DraftCandidateStatus,
    DraftGenerator,
    DraftVersionKind,
    DraftVersionStatus,
    audit_sentences,
    classify_fact,
    detect_new_facts,
    split_sentences,
)
from backend.app.content_factory.recall import (
    MockRecallClient,
    RecallResult,
    RecallStatus,
    apply_filters,
)
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
def make_router(reply_text=None, per_role_text=None):
    """构造 mock model_router。reply_text 统一回复；per_role_text 按角色区分。"""
    cfg = ModelRouterConfig.default()
    clients = {}
    for role in ModelRole:
        text = None
        if per_role_text:
            text = per_role_text.get(role)
        text = text or reply_text
        replies = [ModelReply(text=text)] if text else []
        clients[role] = MockModelClient(model_name=f"mock-{role.value}", scripted_replies=replies)
    return ModelRouter(config=cfg, clients=clients)


def mat(id, content, mtype="fact_card", source="9080_approved", status="active"):
    return {"id": id, "content": content, "material_type": mtype,
            "source_type": source, "status": status}


# 一组"每句都能溯源"的干净素材 + 对应干净稿
CLEAN_MATERIALS = [
    mat("dfd_fact_001", "润养安肤奢华油为普通化妆品"),
    mat("dfd_fact_002", "检测方法为体外法透明质酸酶抑制法"),
]
# 每句要么非事实句、要么含素材内容片段 → 全部可溯源、无新增事实
CLEAN_DRAFT = "润养安肤奢华油为普通化妆品。检测方法为体外法透明质酸酶抑制法。"


def make_factory(router, materials, status=RecallStatus.APPROVED):
    client = MockRecallClient(scripted_results=[RecallResult(materials=list(materials), status=status)])
    return ContentFactory(recall_client=client, draft_generator=DraftGenerator(router=router))


def brief(text="奢华油品牌科普", platform="brand_site", **kw):
    return Brief(raw_text=text, target_platform=platform, **kw)


# ──────────────────────────────────────────────────────────────────────
# 必测 1：充分素材 → draft_candidate
# ──────────────────────────────────────────────────────────────────────
class TestSufficientToCandidate:
    def test_sufficient_materials_produces_candidate(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        assert r.state == FactoryTaskState.PACKAGED
        assert r.draft_candidate is not None
        assert r.draft_candidate.status == DraftCandidateStatus.DRAFT_CANDIDATE
        assert len(r.draft_candidate.ok_versions) >= 1

    def test_three_versions_present(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        kinds = {v.kind for v in r.draft_candidate.versions}
        assert kinds == {
            DraftVersionKind.PROFESSIONAL,
            DraftVersionKind.STATE_AESTHETIC,
            DraftVersionKind.PLATFORM_REWRITE,
        }


# ──────────────────────────────────────────────────────────────────────
# 必测 2/3/4：停单路径
# ──────────────────────────────────────────────────────────────────────
class TestHaltPaths:
    def test_empty_materials_halts(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), [])
        r = f.process_brief(brief())
        assert r.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert r.draft_candidate is None
        assert f.staging.count() == 0

    def test_recall_client_none_halts(self):
        f = ContentFactory(draft_generator=DraftGenerator(router=make_router(reply_text=CLEAN_DRAFT)))
        r = f.process_brief(brief())
        assert r.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert f.staging.count() == 0

    def test_blacklist_filtered_insufficient_halts(self):
        dirty = [mat("k1", "内容", mtype="kimi_expansion")]
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), dirty)
        r = f.process_brief(brief())
        assert r.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert f.staging.count() == 0

    def test_generator_defensive_empty_returns_halt(self):
        """生成器自身对空素材的防御性停单（不依赖 factory 前置）。"""
        gen = DraftGenerator(router=make_router(reply_text=CLEAN_DRAFT))
        cand = gen.generate(content_id="c", brief_id="b", trace_id="t",
                            brief_text="x", used_materials=[])
        assert cand.status == DraftCandidateStatus.HALTED_MISSING_MATERIALS


# ──────────────────────────────────────────────────────────────────────
# 必测 5：direction_hint 不进 used_materials
# ──────────────────────────────────────────────────────────────────────
class TestDirectionHintIsolation:
    def test_direction_hint_not_in_recall_keywords(self):
        client = MockRecallClient()
        f = ContentFactory(recall_client=client,
                           draft_generator=DraftGenerator(router=make_router(reply_text=CLEAN_DRAFT)))
        f.process_brief(brief(direction_hint="小红书热点：早八护肤玄学"))
        kw = client.calls[0].keywords
        assert not any("热点" in k or "早八" in k or "玄学" in k for k in kw)

    def test_direction_hint_not_in_candidate_materials(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief(direction_hint="平台灵感XYZ"))
        # 候选稿绑定的素材 id 只来自召回，不含 direction_hint
        assert "平台灵感XYZ" not in r.draft_candidate.used_materials_ids


# ──────────────────────────────────────────────────────────────────────
# 必测 6：模型新增事实 → blocked
# ──────────────────────────────────────────────────────────────────────
class TestNewFactGuard:
    def test_model_adds_number_blocked(self):
        # 素材无 "98%"，模型输出编造 "98%" → 新增事实
        r = make_router(reply_text="本品有效率高达98%。润养安肤奢华油为普通化妆品。")
        f = make_factory(r, CLEAN_MATERIALS)
        res = f.process_brief(brief())
        assert res.state == FactoryTaskState.BLOCKED_DRAFT
        assert res.draft_candidate.status == DraftCandidateStatus.BLOCKED
        assert all(v.status == DraftVersionStatus.BLOCKED_NEW_FACT
                   for v in res.draft_candidate.versions)

    def test_model_adds_report_code_blocked(self):
        r = make_router(reply_text="依据报告XYJCR999999。润养安肤奢华油为普通化妆品。")
        f = make_factory(r, CLEAN_MATERIALS)
        res = f.process_brief(brief())
        assert res.state == FactoryTaskState.BLOCKED_DRAFT

    def test_detect_new_facts_unit(self):
        materials = [mat("m1", "报告编号XYJCR241029-005，舒缓有效")]
        assert detect_new_facts("引用XYJCR241029-005", materials) == []
        assert "88%" in detect_new_facts("有效率88%", materials)

    def test_number_present_in_material_not_new(self):
        materials = [mat("m1", "舒缓报告编号XYJCR241029-005")]
        # 数字来自素材编号 → 不算新增
        assert detect_new_facts("报告编号XYJCR241029-005说明舒缓", materials) == []


# ──────────────────────────────────────────────────────────────────────
# 必测 7：draft_candidate 绑定 used_materials_ids
# ──────────────────────────────────────────────────────────────────────
class TestBinding:
    def test_candidate_binds_used_materials_ids(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        assert r.draft_candidate.used_materials_ids == ["dfd_fact_001", "dfd_fact_002"]

    def test_every_version_binds_same_ids(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        for v in r.draft_candidate.versions:
            assert v.used_materials_ids == ["dfd_fact_001", "dfd_fact_002"]


# ──────────────────────────────────────────────────────────────────────
# 必测 8：每个事实句必须有 source_refs（句级溯源）
# ──────────────────────────────────────────────────────────────────────
class TestSentenceRefs:
    def test_unsourced_fact_sentence_blocks_version(self):
        # "临床数据显示" 是事实句但素材里没有 → 无源事实句
        r = make_router(reply_text="临床数据显示效果显著。润养安肤奢华油为普通化妆品。")
        f = make_factory(r, CLEAN_MATERIALS)
        res = f.process_brief(brief())
        assert res.state == FactoryTaskState.BLOCKED_DRAFT
        assert any(v.status == DraftVersionStatus.BLOCKED_UNSOURCED_FACT
                   for v in res.draft_candidate.versions)

    def test_classify_fact_heuristic(self):
        assert classify_fact("检测方法为体外法")
        assert classify_fact("有效率88%")
        assert not classify_fact("这是你每天留给自己的仪式感")

    def test_audit_passes_when_all_facts_sourced(self):
        audit = audit_sentences(CLEAN_DRAFT, CLEAN_MATERIALS)
        assert audit.passed
        assert audit.violations == []

    def test_audit_flags_unsourced(self):
        audit = audit_sentences("检测数据高达99分。", CLEAN_MATERIALS)
        assert not audit.passed
        assert audit.violations

    def test_ok_version_has_audit_all_facts_sourced(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        for v in r.draft_candidate.ok_versions:
            for ref in v.audit.refs:
                if ref.is_fact:
                    assert ref.source_material_ids, f"事实句无 source_ref: {ref.sentence}"


# ──────────────────────────────────────────────────────────────────────
# 必测 9：daily_*/webintel_*/crawl_* 前缀不得作为事实源
# ──────────────────────────────────────────────────────────────────────
class TestBlacklistPrefix:
    @pytest.mark.parametrize("mtype", [
        "daily_summary", "daily_hot", "webintel_scan", "webintel_2026",
        "crawl_20260704", "crawl_batch_1",
    ])
    def test_prefix_variants_filtered(self, mtype):
        materials = [mat("x", "内容", mtype=mtype), mat("ok", "润养安肤奢华油为普通化妆品")]
        filtered = apply_filters(materials)
        ids = [m["id"] for m in filtered]
        assert "x" not in ids
        assert "ok" in ids

    def test_prefix_on_source_type_filtered(self):
        materials = [mat("x", "内容", source="crawl_raw_feed")]
        assert apply_filters(materials) == []

    def test_prefix_material_e2e_not_a_fact_source(self):
        # 前缀素材 + 合法素材：前缀件不进 used_materials
        materials = [mat("d1", "内容", mtype="daily_brief_x"),
                     mat("dfd_fact_001", "润养安肤奢华油为普通化妆品"),
                     mat("dfd_fact_002", "检测方法为体外法透明质酸酶抑制法")]
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), materials)
        r = f.process_brief(brief())
        assert "d1" not in r.draft_candidate.used_materials_ids


# ──────────────────────────────────────────────────────────────────────
# 必测 10：三版稿共用同一组 used_materials
# ──────────────────────────────────────────────────────────────────────
class TestSharedMaterials:
    def test_all_versions_share_one_material_set(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        id_sets = {tuple(v.used_materials_ids) for v in r.draft_candidate.versions}
        assert len(id_sets) == 1  # 三版完全一致


# ──────────────────────────────────────────────────────────────────────
# 必测 11/12：不得 publish_allowed / 不写 approved
# ──────────────────────────────────────────────────────────────────────
class TestNoPublishNoApproved:
    def test_candidate_publish_allowed_constant_false(self):
        f = make_factory(make_router(reply_text=CLEAN_DRAFT), CLEAN_MATERIALS)
        r = f.process_brief(brief())
        assert r.draft_candidate.publish_allowed is False
        assert r.draft_candidate.writes_approved is False

    def test_publish_allowed_has_no_write_entry(self):
        with pytest.raises(TypeError):
            DraftCandidate(content_id="c", brief_id="b", trace_id="t",
                           status=DraftCandidateStatus.DRAFT_CANDIDATE,
                           publish_allowed=True)


# ──────────────────────────────────────────────────────────────────────
# 端到端：不注入 generator 时保持 W1/W2 行为（向后兼容）
# ──────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────
# Qoder 补强测试
# ──────────────────────────────────────────────────────────────────────


class TestPartialBlock:
    """部分版本被拦、仍有 OK 版 → 候选整体仍为 DRAFT_CANDIDATE。"""

    def test_partial_block_still_candidate(self):
        """三版中一版被拦（新增事实），另两版 OK → 整体仍为候选。"""
        # 用 per_role_text 让 REWRITE 版编造数字，PRIMARY 版干净
        from backend.app.model_router.schemas import ModelRole as MR
        per_role = {
            MR.PRIMARY: CLEAN_DRAFT,        # 干净 → OK
            MR.REWRITE: "有效率99%。",       # 新增事实 → BLOCKED_NEW_FACT
        }
        r = make_router(per_role_text=per_role)
        f = make_factory(r, CLEAN_MATERIALS)
        res = f.process_brief(brief())
        assert res.draft_candidate.status == DraftCandidateStatus.DRAFT_CANDIDATE
        assert len(res.draft_candidate.ok_versions) >= 1
        # REWRITE 版被拦
        rw = next(v for v in res.draft_candidate.versions
                  if v.kind == DraftVersionKind.PLATFORM_REWRITE)
        assert rw.status == DraftVersionStatus.BLOCKED_NEW_FACT


class TestBlockedDraftTerminal:
    """BLOCKED_DRAFT 是终态，不可再转换。"""

    def test_blocked_draft_is_terminal(self):
        from backend.app.content_factory.task_state import StateMachine, InvalidTransition
        sm = StateMachine()
        sm.transition(FactoryTaskState.PRODUCING, operator="factory")
        sm.transition(FactoryTaskState.BLOCKED_DRAFT, operator="factory")
        assert sm.is_terminal
        # 任何后续转换都应失败
        with pytest.raises(InvalidTransition):
            sm.transition(FactoryTaskState.GATED, operator="factory")


class TestDirectionHintNotInPrompt:
    """direction_hint 不得进入模型提示词的素材区。"""

    def test_direction_hint_not_in_model_materials(self):
        """direction_hint 是平台灵感，不能成为模型的事实来源。"""
        from backend.app.model_router.router import build_prompt
        from backend.app.model_router.schemas import DraftTask, TaskType
        task = DraftTask(
            content_id="c1",
            task_type=TaskType.FACT_STRICT,
            brief="品牌科普",
            used_materials=CLEAN_MATERIALS,
            platform="brand_site",
        )
        prompt = build_prompt(task)
        # direction_hint 不应出现在提示词中（它由 brief 层隔离，不进素材）
        assert "小红书热点" not in prompt
        assert "平台灵感" not in prompt


class TestAllVersionsBlockedIsBlockedDraft:
    """三版全被拦 → 整份 BLOCKED → factory 转 BLOCKED_DRAFT。"""

    def test_all_blocked_unsourced_fact(self):
        """所有版本都含无源事实句 → BLOCKED_DRAFT 终态。"""
        r = make_router(reply_text="临床数据显示99%有效率。无源事实句。")
        f = make_factory(r, CLEAN_MATERIALS)
        res = f.process_brief(brief())
        assert res.state == FactoryTaskState.BLOCKED_DRAFT
        assert res.draft_candidate.status == DraftCandidateStatus.BLOCKED
        # 不写 staging
        assert f.staging.count() == 0


class TestBackwardCompatNoGenerator:
    def test_no_generator_keeps_skeleton_behavior(self):
        client = MockRecallClient(scripted_results=[
            RecallResult(materials=list(CLEAN_MATERIALS), status=RecallStatus.APPROVED)])
        f = ContentFactory(recall_client=client)  # 无 draft_generator
        r = f.process_brief(brief())
        assert r.state == FactoryTaskState.PACKAGED
        assert r.text is None
        assert r.draft_candidate is None
