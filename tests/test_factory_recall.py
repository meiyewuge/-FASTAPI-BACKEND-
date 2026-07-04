"""W2 测试 — 9080 只读召回 + 过滤 + 绑定 + 日志 + Patch C。

覆盖 M1 W2 9080 只读召回适配 + Claude Code V2 Patch C：
- MockRecallClient 返回正确结构
- 白名单过滤（fail-closed）
- 黑名单过滤（含 M1 黑名单）
- used_materials 绑定 + source_refs
- 缺料报告
- 召回日志 14 字段完整
- 默认配置 mock=True
- fail-closed：缺 material_type / source_type / status → 拒绝
"""
import pytest

from backend.app.content_factory.recall import (
    BoundMaterials,
    DEFAULT_BLACKLIST,
    DEFAULT_WHITELIST,
    FilterReport,
    MockRecallClient,
    RECALL_REQUIRED_FIELDS,
    RecallConfig,
    RecallLog,
    RecallLogEntry,
    RecallMetadata,
    RecallQuery,
    RecallResult,
    RecallStatus,
    SourceRef,
    SourceType,
    apply_filters,
    apply_filters_with_report,
    bind_materials,
)
from backend.app.content_factory.schemas import Brief
from backend.app.model_router.schemas import MissingMaterialReport, TaskType


# ──────────────────────────────────────────────────────────────────────
# MockRecallClient
# ──────────────────────────────────────────────────────────────────────
class TestMockRecallClient:
    def test_default_returns_missing(self):
        client = MockRecallClient()
        result = client.recall(RecallQuery(brief_id="b1", keywords=["品牌"]))
        assert result.status == RecallStatus.MISSING
        assert result.materials == []
        assert len(client.calls) == 1

    def test_scripted_result(self):
        scripted = RecallResult(
            materials=[{"id": "m1", "content": "事实卡"}],
            status=RecallStatus.APPROVED,
        )
        client = MockRecallClient(scripted_results=[scripted])
        result = client.recall(RecallQuery(brief_id="b1"))
        assert result.status == RecallStatus.APPROVED
        assert len(result.materials) == 1

    def test_config_default_mock_true(self):
        assert RecallConfig().mock is True
        assert RecallConfig().base_url == "mock"

    def test_scripted_exhaust_returns_empty(self):
        client = MockRecallClient()
        r1 = client.recall(RecallQuery(brief_id="b1"))
        r2 = client.recall(RecallQuery(brief_id="b2"))
        assert r1.status == RecallStatus.MISSING
        assert r2.status == RecallStatus.MISSING


# ──────────────────────────────────────────────────────────────────────
# 白名单过滤
# ──────────────────────────────────────────────────────────────────────
class TestWhitelistFilter:
    def test_whitelist_keeps_allowed_types(self):
        materials = [
            {"id": "m1", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "compliance_rule",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m3", "material_type": "random_type",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials)
        ids = [m["id"] for m in filtered]
        assert "m1" in ids
        assert "m2" in ids
        assert "m3" not in ids

    def test_whitelist_custom(self):
        materials = [
            {"id": "m1", "material_type": "custom_type",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=["custom_type"])
        assert len(filtered) == 1
        assert filtered[0]["id"] == "m1"

    def test_empty_whitelist_no_filter(self):
        materials = [
            {"id": "m1", "material_type": "anything",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[], blacklist=[])
        assert len(filtered) == 1


# ──────────────────────────────────────────────────────────────────────
# 黑名单过滤
# ──────────────────────────────────────────────────────────────────────
class TestBlacklistFilter:
    def test_blacklist_removes_blocked_types(self):
        materials = [
            {"id": "m1", "material_type": "draft",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m3", "material_type": "rejected",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        ids = [m["id"] for m in filtered]
        assert "m1" not in ids
        assert "m2" in ids
        assert "m3" not in ids

    def test_blacklist_by_status(self):
        materials = [
            {"id": "m1", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "archived"},
            {"id": "m2", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 1
        assert filtered[0]["id"] == "m2"

    def test_filter_with_report(self):
        materials = [
            {"id": "m1", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "draft",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m3", "material_type": "unknown",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered, report = apply_filters_with_report(materials)
        assert isinstance(report, FilterReport)
        assert report.before_count == 3
        assert report.after_count == 1
        assert report.removed_count == 2
        assert report.whitelist_applied == DEFAULT_WHITELIST
        assert report.blacklist_applied == DEFAULT_BLACKLIST


# ──────────────────────────────────────────────────────────────────────
# used_materials 绑定
# ──────────────────────────────────────────────────────────────────────
class TestBindMaterials:
    def test_sufficient_materials(self):
        result = RecallResult(
            materials=[{"id": "m1", "content": "事实卡"}],
            status=RecallStatus.APPROVED,
            source_refs=[SourceRef(material_id="m1")],
        )
        brief = Brief(raw_text="品牌科普", task_type=TaskType.FACT_STRICT, target_platform="brand_site")
        bound = bind_materials(result, brief)
        assert bound.is_sufficient is True
        assert bound.missing_report is None
        assert bound.material_ids == ["m1"]
        assert len(bound.source_refs) == 1

    def test_missing_materials(self):
        result = RecallResult(materials=[], status=RecallStatus.MISSING)
        brief = Brief(raw_text="品牌科普", task_type=TaskType.FACT_STRICT, target_platform="brand_site")
        bound = bind_materials(result, brief)
        assert bound.is_sufficient is False
        assert isinstance(bound.missing_report, MissingMaterialReport)

    def test_insufficient_materials_for_high_risk(self):
        result = RecallResult(
            materials=[{"id": "m1", "content": "唯一素材"}],
            status=RecallStatus.APPROVED,
        )
        brief = Brief(raw_text="敏感肌科普", task_type=TaskType.HIGH_RISK, target_platform="brand_site")
        bound = bind_materials(result, brief)
        # HIGH_RISK 需要 ≥2 素材
        assert bound.is_sufficient is False
        assert bound.missing_report is not None

    def test_blocked_recall(self):
        result = RecallResult(materials=[], status=RecallStatus.BLOCKED)
        brief = Brief(raw_text="测试", task_type=TaskType.FACT_STRICT, target_platform="brand_site")
        bound = bind_materials(result, brief)
        assert bound.is_sufficient is False
        assert "拦截" in bound.missing_report.missing_material_types[0]


# ──────────────────────────────────────────────────────────────────────
# SourceRef
# ──────────────────────────────────────────────────────────────────────
class TestSourceRef:
    def test_source_ref_defaults(self):
        ref = SourceRef(material_id="m1")
        assert ref.source_type == SourceType.APPROVED_9080
        assert ref.source_version == "v1"
        assert ref.recalled_at  # 非空


# ──────────────────────────────────────────────────────────────────────
# 召回日志
# ──────────────────────────────────────────────────────────────────────
class TestRecallLog:
    def test_all_required_fields_present(self):
        log = RecallLog()
        entry = log.record(
            brief_id="b1", trace_id="t1",
            query_keywords=["品牌", "科普"],
            material_types_requested=["fact_card"],
            materials_returned=3,
            filtered_count=1,
            status="approved",
            latency_ms=50,
            source_refs_count=3,
            whitelist_applied=DEFAULT_WHITELIST,
            blacklist_applied=DEFAULT_BLACKLIST,
        )
        for f in RECALL_REQUIRED_FIELDS:
            assert hasattr(entry, f), f"缺少必记字段 {f}"

    def test_query_by_brief(self):
        log = RecallLog()
        log.record(brief_id="b1", trace_id="t1", query_keywords=[],
                   material_types_requested=None, materials_returned=1,
                   filtered_count=0, status="approved")
        log.record(brief_id="b2", trace_id="t2", query_keywords=[],
                   material_types_requested=None, materials_returned=0,
                   filtered_count=0, status="missing")
        assert len(log.query_by_brief("b1")) == 1
        assert len(log.query_by_brief("b2")) == 1

    def test_query_by_trace(self):
        log = RecallLog()
        log.record(brief_id="b1", trace_id="t1", query_keywords=[],
                   material_types_requested=None, materials_returned=1,
                   filtered_count=0, status="approved")
        assert len(log.query_by_trace("t1")) == 1
        assert len(log.query_by_trace("nonexistent")) == 0

    def test_summary(self):
        log = RecallLog()
        log.record(brief_id="b1", trace_id="t1", query_keywords=[],
                   material_types_requested=None, materials_returned=1,
                   filtered_count=0, status="approved")
        log.record(brief_id="b2", trace_id="t2", query_keywords=[],
                   material_types_requested=None, materials_returned=0,
                   filtered_count=0, status="missing")
        log.record(brief_id="b3", trace_id="t3", query_keywords=[],
                   material_types_requested=None, materials_returned=2,
                   filtered_count=0, status="approved")
        summary = log.summary()
        assert summary["approved"] == 2
        assert summary["missing"] == 1


# ──────────────────────────────────────────────────────────────────────
# Patch C: fail-closed + M1 黑名单
# ──────────────────────────────────────────────────────────────────────
class TestFailClosed:
    def test_missing_material_type_rejected(self):
        """缺 material_type → 拒绝。"""
        materials = [
            {"id": "m1", "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "m2"

    def test_missing_source_type_rejected(self):
        """缺 source_type → 拒绝。"""
        materials = [
            {"id": "m1", "material_type": "fact_card", "status": "active"},
            {"id": "m2", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "m2"

    def test_missing_status_rejected(self):
        """缺 status → 拒绝。"""
        materials = [
            {"id": "m1", "material_type": "fact_card",
             "source_type": "9080_approved"},
            {"id": "m2", "material_type": "fact_card",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "m2"


class TestM1Blacklist:
    def test_kimi_expansion_blocked(self):
        """Kimi 扩写件不得进入事实材料。"""
        materials = [
            {"id": "m1", "material_type": "kimi_expansion",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0

    def test_daily_brief_blocked(self):
        materials = [
            {"id": "m1", "material_type": "daily_brief",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0

    def test_webintel_blocked(self):
        materials = [
            {"id": "m1", "material_type": "webintel",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "webintel_crawl",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0

    def test_crawl_blocked(self):
        materials = [
            {"id": "m1", "material_type": "crawl_raw",
             "source_type": "9080_approved", "status": "active"},
            {"id": "m2", "material_type": "crawl_unverified",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0

    def test_craft_memory_blocked(self):
        materials = [
            {"id": "m1", "material_type": "craft_memory",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0

    def test_platform_inspiration_as_fact_blocked(self):
        materials = [
            {"id": "m1", "material_type": "platform_inspiration_as_fact",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0

    def test_raw_draft_blocked(self):
        materials = [
            {"id": "m1", "material_type": "raw_draft",
             "source_type": "9080_approved", "status": "active"},
        ]
        filtered = apply_filters(materials, whitelist=[])
        assert len(filtered) == 0
