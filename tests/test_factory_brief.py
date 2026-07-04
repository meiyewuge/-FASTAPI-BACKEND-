"""W1 测试 — Brief 理解层 + 状态机 + Staging + 工厂骨架。

覆盖 M1 W1 服务骨架 + Claude Code V2 Patch A/B：
- Brief 解析正反样例（含 target_platform / line / direction_hint）
- 批量 Brief 解析
- 状态机 7 态合法流转（含缺料停单态）
- 状态机非法跳态拦截
- trace_id / task_id / brief_id 绑定
- staging put / get / list
- factory 骨架 process_brief 返回正确结构
- 缺料停单：零素材 → HALTED_MISSING_MATERIALS
- Brief 边界字段验证
"""
import pytest

from backend.app.content_factory import (
    Brief,
    BriefParseError,
    ContentFactory,
    ContentStaging,
    ContentStagingEntry,
    FactoryResult,
    FactoryTaskState,
    InvalidPlatformError,
    InvalidTransition,
    StateMachine,
    TraceContext,
    parse_brief,
    parse_batch_briefs,
)
from backend.app.model_router.schemas import TaskType


# ──────────────────────────────────────────────────────────────────────
# Brief 解析
# ──────────────────────────────────────────────────────────────────────
class TestBriefParsing:
    def test_parse_valid_brief(self):
        b = parse_brief({"raw_text": "写一篇品牌科普", "task_type": "fact_strict",
                         "target_platform": "xiaohongshu"})
        assert isinstance(b, Brief)
        assert b.raw_text == "写一篇品牌科普"
        assert b.task_type == TaskType.FACT_STRICT
        assert b.target_platform == "xiaohongshu"
        assert b.line == "brand_dfd"
        assert b.brief_id.startswith("brief_")
        assert b.trace_id.startswith("trace_")

    def test_parse_brief_default_task_type(self):
        b = parse_brief({"raw_text": "写一篇文案", "target_platform": "brand_site"})
        assert b.task_type == TaskType.FACT_STRICT

    def test_parse_brief_empty_text_fails(self):
        with pytest.raises(BriefParseError, match="raw_text"):
            parse_brief({"raw_text": ""})

    def test_parse_brief_missing_text_fails(self):
        with pytest.raises(BriefParseError, match="raw_text"):
            parse_brief({})

    def test_parse_brief_invalid_task_type(self):
        with pytest.raises(BriefParseError, match="非法 task_type"):
            parse_brief({"raw_text": "test", "task_type": "nonexistent"})

    def test_parse_brief_not_dict_fails(self):
        with pytest.raises(BriefParseError, match="字典"):
            parse_brief("not a dict")

    def test_parse_brief_with_all_fields(self):
        b = parse_brief({
            "raw_text": "  写一篇小红书改写  ",
            "task_type": "platform_rewrite",
            "target_platform": "xiaohongshu",
            "line": "brand_dfd",
            "direction_hint": "热门护肤话题",
            "target_audience": "25-35 女性",
            "risk_hint": None,
            "batch_id": "batch_001",
        })
        assert b.raw_text == "写一篇小红书改写"  # 去空格
        assert b.task_type == TaskType.PLATFORM_REWRITE
        assert b.target_platform == "xiaohongshu"
        assert b.direction_hint == "热门护肤话题"
        assert b.batch_id == "batch_001"


# ──────────────────────────────────────────────────────────────────────
# 批量 Brief
# ──────────────────────────────────────────────────────────────────────
class TestBatchBriefs:
    def test_parse_batch(self):
        raws = [
            {"raw_text": "品牌科普 A", "target_platform": "brand_site"},
            {"raw_text": "品牌科普 B", "task_type": "state_aesthetic",
             "target_platform": "brand_site"},
        ]
        briefs = parse_batch_briefs(raws)
        assert len(briefs) == 2
        assert briefs[0].task_type == TaskType.FACT_STRICT
        assert briefs[1].task_type == TaskType.STATE_AESTHETIC
        # 自动分配 batch_id
        assert briefs[0].batch_id is not None
        assert briefs[0].batch_id == briefs[1].batch_id

    def test_parse_batch_one_fails(self):
        raws = [
            {"raw_text": "正常 Brief", "target_platform": "brand_site"},
            {"raw_text": ""},  # 失败
        ]
        with pytest.raises(BriefParseError, match="Brief\\[1\\]"):
            parse_batch_briefs(raws)

    def test_parse_batch_preserves_existing_batch_id(self):
        raws = [{"raw_text": "A", "batch_id": "my_batch",
                 "target_platform": "brand_site"}]
        briefs = parse_batch_briefs(raws)
        assert briefs[0].batch_id == "my_batch"


# ──────────────────────────────────────────────────────────────────────
# 状态机
# ──────────────────────────────────────────────────────────────────────
class TestStateMachine:
    def test_happy_path_full_flow(self):
        sm = StateMachine()
        assert sm.current == FactoryTaskState.QUEUED

        sm.transition(FactoryTaskState.PRODUCING, operator="factory")
        assert sm.current == FactoryTaskState.PRODUCING

        sm.transition(FactoryTaskState.GATED, operator="gate")
        sm.transition(FactoryTaskState.PACKAGED, operator="factory")
        sm.transition(FactoryTaskState.IN_REVIEW, operator="reviewer")
        sm.transition(FactoryTaskState.CLOSED, operator="吴哥", note="签发通过")

        assert sm.is_terminal
        assert len(sm.history) == 5
        assert sm.history[-1].operator == "吴哥"
        assert sm.history[-1].note == "签发通过"

    def test_skip_state_rejected(self):
        sm = StateMachine()
        with pytest.raises(InvalidTransition, match="非法状态转换"):
            sm.transition(FactoryTaskState.CLOSED)

    def test_backward_rejected(self):
        sm = StateMachine()
        sm.transition(FactoryTaskState.PRODUCING)
        with pytest.raises(InvalidTransition):
            sm.transition(FactoryTaskState.QUEUED)

    def test_closed_is_terminal(self):
        sm = StateMachine(current=FactoryTaskState.CLOSED)
        assert sm.is_terminal
        assert sm.allowed_next == []
        with pytest.raises(InvalidTransition):
            sm.transition(FactoryTaskState.QUEUED)

    def test_allowed_next(self):
        sm = StateMachine()
        assert sm.allowed_next == [FactoryTaskState.PRODUCING]


# ──────────────────────────────────────────────────────────────────────
# 三 ID 溯源
# ──────────────────────────────────────────────────────────────────────
class TestTraceContext:
    def test_from_brief(self):
        b = Brief(raw_text="test", target_platform="brand_site")
        ctx = TraceContext.from_brief(b)
        assert ctx.trace_id == b.trace_id
        assert ctx.brief_id == b.brief_id
        assert ctx.task_id.startswith("task_")


# ──────────────────────────────────────────────────────────────────────
# Staging
# ──────────────────────────────────────────────────────────────────────
class TestStaging:
    def test_put_and_get(self):
        s = ContentStaging()
        entry = ContentStagingEntry(
            content_id="c1", brief_id="b1", trace_id="t1",
            state=FactoryTaskState.PACKAGED, text="草稿",
        )
        s.put(entry)
        assert s.get("c1") is entry
        assert s.count() == 1

    def test_list_by_brief(self):
        s = ContentStaging()
        s.put(ContentStagingEntry(content_id="c1", brief_id="b1", trace_id="t1"))
        s.put(ContentStagingEntry(content_id="c2", brief_id="b1", trace_id="t1"))
        s.put(ContentStagingEntry(content_id="c3", brief_id="b2", trace_id="t2"))
        assert len(s.list_by_brief("b1")) == 2
        assert len(s.list_by_brief("b2")) == 1

    def test_list_by_state(self):
        s = ContentStaging()
        s.put(ContentStagingEntry(content_id="c1", brief_id="b1", trace_id="t1",
                                  state=FactoryTaskState.QUEUED))
        s.put(ContentStagingEntry(content_id="c2", brief_id="b1", trace_id="t1",
                                  state=FactoryTaskState.PACKAGED))
        assert len(s.list_by_state(FactoryTaskState.QUEUED)) == 1
        assert len(s.list_by_state(FactoryTaskState.PACKAGED)) == 1


# ──────────────────────────────────────────────────────────────────────
# 工厂骨架
# ──────────────────────────────────────────────────────────────────────
class TestFactorySkeleton:
    def test_process_brief_without_recall(self):
        """Patch D: 默认 ContentFactory() 无 recall_client → 停单。"""
        factory = ContentFactory()
        brief = Brief(raw_text="写一篇品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        assert isinstance(result, FactoryResult)
        assert result.content_id.startswith("content_")
        assert result.brief_id == brief.brief_id
        assert result.trace_id == brief.trace_id
        assert result.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert result.text is None
        assert result.used_materials_ids == []
        assert result.missing_report is not None
        assert "recall_client_not_configured" in result.missing_report.missing_material_types
        # staging 不写入候选态
        assert factory.staging.count() == 0

    def test_process_brief_writes_staging(self):
        """显式 mock recall_client + 素材充分时才允许 PACKAGED + staging。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus, RecallMetadata,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(
                    materials=[
                        {"id": "m1", "content": "事实卡",
                         "material_type": "fact_card",
                         "source_type": "9080_approved", "status": "active"},
                    ],
                    status=RecallStatus.APPROVED,
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="写一篇品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        assert result.state == FactoryTaskState.PACKAGED
        entry = factory.staging.get(result.content_id)
        assert entry is not None
        assert entry.brief_id == brief.brief_id
        assert entry.state == FactoryTaskState.PACKAGED

    def test_process_brief_with_mock_recall(self):
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus, RecallMetadata,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(
                    materials=[
                        {"id": "mat_001", "content": "事实卡内容",
                         "material_type": "fact_card", "source_type": "9080_approved",
                         "status": "active"},
                        {"id": "mat_002", "content": "合规规则",
                         "material_type": "compliance_rule", "source_type": "9080_approved",
                         "status": "active"},
                    ],
                    status=RecallStatus.APPROVED,
                    metadata=RecallMetadata(query_hash="test"),
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="写一篇品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        assert result.recall_summary["status"] == "approved"
        assert result.recall_summary["materials_count"] == 2
        assert result.used_materials_ids == ["mat_001", "mat_002"]
        assert len(mock_client.calls) == 1


# ──────────────────────────────────────────────────────────────────────
# Patch A: 缺料停单
# ──────────────────────────────────────────────────────────────────────
class TestHaltedMissingMaterials:
    def test_zero_materials_halted(self):
        """零素材 → 缺料停单，不进 PACKAGED。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus, RecallMetadata,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(
                    materials=[],
                    status=RecallStatus.MISSING,
                    metadata=RecallMetadata(query_hash="test"),
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="写一篇品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        assert result.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert result.text is None
        assert result.used_materials_ids == []
        assert result.missing_report is not None

    def test_halted_not_in_staging_candidate(self):
        """缺料停单后不进入可被后续出稿使用的 staging 候选态。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus, RecallMetadata,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(materials=[], status=RecallStatus.MISSING),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        # staging 中不应有 PACKAGED 状态的条目
        packaged_entries = factory.staging.list_by_state(FactoryTaskState.PACKAGED)
        assert len(packaged_entries) == 0
        # halted 状态不应出现在 staging
        assert result.state == FactoryTaskState.HALTED_MISSING_MATERIALS

    def test_blocked_recall_halted(self):
        """召回被拦截 → 缺料停单。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(materials=[], status=RecallStatus.BLOCKED),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="敏感肌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        assert result.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert result.missing_report is not None

    def test_halted_is_terminal(self):
        """缺料停单是终态。"""
        sm = StateMachine()
        sm.transition(FactoryTaskState.PRODUCING)
        sm.transition(FactoryTaskState.HALTED_MISSING_MATERIALS)
        assert sm.is_terminal
        assert sm.allowed_next == []


# ──────────────────────────────────────────────────────────────────────
# Patch B: Brief 边界字段验证
# ──────────────────────────────────────────────────────────────────────
class TestBriefBoundaryFields:
    def test_missing_platform_fails(self):
        with pytest.raises(BriefParseError, match="target_platform"):
            parse_brief({"raw_text": "test"})

    def test_invalid_platform_fails(self):
        with pytest.raises(InvalidPlatformError, match="非法 target_platform"):
            parse_brief({"raw_text": "test", "target_platform": "weibo"})

    def test_valid_platforms_accepted(self):
        for p in ["brand_site", "xiaohongshu", "douyin", "shipinhao"]:
            b = parse_brief({"raw_text": "test", "target_platform": p})
            assert b.target_platform == p

    def test_line_non_brand_dfd_rejected(self):
        with pytest.raises(BriefParseError, match="M1 锁死"):
            parse_brief({"raw_text": "test", "target_platform": "brand_site",
                         "line": "other_brand"})

    def test_line_default_brand_dfd(self):
        b = parse_brief({"raw_text": "test", "target_platform": "brand_site"})
        assert b.line == "brand_dfd"

    def test_direction_hint_stored(self):
        b = parse_brief({"raw_text": "test", "target_platform": "brand_site",
                         "direction_hint": "小红书热门话题"})
        assert b.direction_hint == "小红书热门话题"

    def test_direction_hint_not_in_used_materials(self):
        """direction_hint 不得进入 used_materials。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(
                    materials=[
                        {"id": "m1", "material_type": "fact_card",
                         "source_type": "9080_approved", "status": "active"},
                    ],
                    status=RecallStatus.APPROVED,
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(
            raw_text="品牌科普",
            target_platform="brand_site",
            direction_hint="热门话题",
        )
        result = factory.process_brief(brief)
        # used_materials_ids 只含素材 ID，不含 direction_hint
        assert "热门话题" not in result.used_materials_ids
        assert result.used_materials_ids == ["m1"]


# ──────────────────────────────────────────────────────────────────────
# Patch D: 默认构造不得绕过缺料停单
# ──────────────────────────────────────────────────────────────────────
class TestPatchD:
    def test_default_factory_halts(self):
        """默认 ContentFactory() → HALTED_MISSING_MATERIALS。"""
        factory = ContentFactory()
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)
        assert result.state == FactoryTaskState.HALTED_MISSING_MATERIALS

    def test_default_factory_no_staging(self):
        """默认 ContentFactory() → 不写 staging。"""
        factory = ContentFactory()
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        factory.process_brief(brief)
        assert factory.staging.count() == 0

    def test_default_factory_missing_report_reason(self):
        """默认 ContentFactory() → missing_report 原因 = recall_client_not_configured。"""
        factory = ContentFactory()
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)
        assert result.missing_report is not None
        assert "recall_client_not_configured" in result.missing_report.missing_material_types

    def test_default_factory_used_materials_empty(self):
        """默认 ContentFactory() → used_materials_ids=[]。"""
        factory = ContentFactory()
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)
        assert result.used_materials_ids == []


# ──────────────────────────────────────────────────────────────────────
# 编排层黑名单注入端到端测试
# ──────────────────────────────────────────────────────────────────────
class TestBlacklistInjectionE2E:
    def test_blacklist_materials_filtered_and_halted(self):
        """kimi_expansion / platform_inspiration_as_fact / raw_draft 注入召回结果
        → 过滤后素材不足 → 停单。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(
                    materials=[
                        {"id": "bad1", "material_type": "kimi_expansion",
                         "source_type": "9080_approved", "status": "active"},
                        {"id": "bad2", "material_type": "platform_inspiration_as_fact",
                         "source_type": "9080_approved", "status": "active"},
                        {"id": "bad3", "material_type": "raw_draft",
                         "source_type": "9080_approved", "status": "active"},
                    ],
                    status=RecallStatus.APPROVED,
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        # 所有素材被黑名单过滤 → 缺料停单
        assert result.state == FactoryTaskState.HALTED_MISSING_MATERIALS
        assert result.used_materials_ids == []
        assert "bad1" not in result.used_materials_ids
        assert "bad2" not in result.used_materials_ids
        assert "bad3" not in result.used_materials_ids

    def test_mixed_materials_only_whitelisted_pass(self):
        """混合素材：只有白名单且非黑名单的素材进入 used_materials。"""
        from backend.app.content_factory.recall import (
            MockRecallClient, RecallResult, RecallStatus,
        )
        mock_client = MockRecallClient(
            scripted_results=[
                RecallResult(
                    materials=[
                        {"id": "good1", "material_type": "fact_card",
                         "source_type": "9080_approved", "status": "active"},
                        {"id": "bad1", "material_type": "kimi_expansion",
                         "source_type": "9080_approved", "status": "active"},
                    ],
                    status=RecallStatus.APPROVED,
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="品牌科普", target_platform="brand_site")
        result = factory.process_brief(brief)

        # good1 通过，bad1 被过滤；素材充分(1≥1)→ 正常 PACKAGED
        assert result.state == FactoryTaskState.PACKAGED
        assert result.used_materials_ids == ["good1"]
        assert "bad1" not in result.used_materials_ids
