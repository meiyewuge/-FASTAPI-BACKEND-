"""W1 测试 — Brief 理解层 + 状态机 + Staging + 工厂骨架。

覆盖 M1 W1 服务骨架：
- Brief 解析正反样例
- 批量 Brief 解析
- 状态机 6 态合法流转
- 状态机非法跳态拦截
- trace_id / task_id / brief_id 绑定
- staging put / get / list
- factory 骨架 process_brief 返回正确结构
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
        b = parse_brief({"raw_text": "写一篇品牌科普", "task_type": "fact_strict"})
        assert isinstance(b, Brief)
        assert b.raw_text == "写一篇品牌科普"
        assert b.task_type == TaskType.FACT_STRICT
        assert b.brief_id.startswith("brief_")
        assert b.trace_id.startswith("trace_")

    def test_parse_brief_default_task_type(self):
        b = parse_brief({"raw_text": "写一篇文案"})
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
            "platform": "xiaohongshu",
            "target_audience": "25-35 女性",
            "risk_hint": None,
            "batch_id": "batch_001",
        })
        assert b.raw_text == "写一篇小红书改写"  # 去空格
        assert b.task_type == TaskType.PLATFORM_REWRITE
        assert b.platform == "xiaohongshu"
        assert b.batch_id == "batch_001"


# ──────────────────────────────────────────────────────────────────────
# 批量 Brief
# ──────────────────────────────────────────────────────────────────────
class TestBatchBriefs:
    def test_parse_batch(self):
        raws = [
            {"raw_text": "品牌科普 A"},
            {"raw_text": "品牌科普 B", "task_type": "state_aesthetic"},
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
            {"raw_text": "正常 Brief"},
            {"raw_text": ""},  # 失败
        ]
        with pytest.raises(BriefParseError, match="Brief\\[1\\]"):
            parse_batch_briefs(raws)

    def test_parse_batch_preserves_existing_batch_id(self):
        raws = [{"raw_text": "A", "batch_id": "my_batch"}]
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
        b = Brief(raw_text="test")
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
        factory = ContentFactory()
        brief = Brief(raw_text="写一篇品牌科普")
        result = factory.process_brief(brief)

        assert isinstance(result, FactoryResult)
        assert result.content_id.startswith("content_")
        assert result.brief_id == brief.brief_id
        assert result.trace_id == brief.trace_id
        assert result.state == FactoryTaskState.PACKAGED
        assert result.text is None  # mock 阶段不出稿
        assert result.recall_summary == {"status": "mock", "materials_count": 0}

    def test_process_brief_writes_staging(self):
        factory = ContentFactory()
        brief = Brief(raw_text="写一篇品牌科普")
        result = factory.process_brief(brief)

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
                        {"id": "mat_001", "content": "事实卡内容"},
                        {"id": "mat_002", "content": "合规规则"},
                    ],
                    status=RecallStatus.APPROVED,
                    metadata=RecallMetadata(query_hash="test"),
                ),
            ]
        )
        factory = ContentFactory(recall_client=mock_client)
        brief = Brief(raw_text="写一篇品牌科普")
        result = factory.process_brief(brief)

        assert result.recall_summary["status"] == "approved"
        assert result.recall_summary["materials_count"] == 2
        assert result.used_materials_ids == ["mat_001", "mat_002"]
        assert len(mock_client.calls) == 1
