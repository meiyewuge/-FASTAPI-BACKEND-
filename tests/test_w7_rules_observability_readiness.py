"""W7 测试 — 真实规则集 / 正式观测接口契约 / 联调准备骨架。

覆盖 M1-W7 条件施工许可 二.1-二.7：
- rulepack md5/签收/生产可用守卫
- G1-G6 外置规则集 + G3 正式契约 + G4 四平台契约
- 观测接口 Protocol + Mock（不写真实库/调度/监控）
- feature flags 全默认 False
- 联调准备 5 清单
"""
import pytest

from backend.app.content_factory.observability import ProductionLineObserver, build_daily_report
from backend.app.content_factory.obs_contracts import (
    AlertLevel, MockAlertSink, MockReportStore, MockScheduler, ScheduledJob,
)
from backend.app.content_factory.readiness import (
    DEFAULT_FLAGS, FeatureFlags, default_checklists,
)
from backend.app.content_factory.rulepacks import (
    EvidenceType, FactClaim, MockFormalG3Adjudicator, PlatformRuleSet, RulePack,
    Rule, RuleAction, RuleSeverity, VALID_PLATFORMS, all_gate_rulepacks, platform_rulesets,
)


# ──────────────────────────────────────────────────────────────────────
# rulepack md5 / 签收 / 生产守卫
# ──────────────────────────────────────────────────────────────────────
class TestRulePackSigning:
    def test_md5_deterministic(self):
        p = RulePack("rp", "0.1.0", "G1_compliance",
                     rules=[Rule("r1", "d", ["治疗"])])
        m1 = p.compute_md5()
        assert m1 == p.compute_md5()  # 稳定
        p.seal()
        assert p.verify_md5()

    def test_md5_changes_on_content_change(self):
        p = RulePack("rp", "0.1.0", "G1_compliance", rules=[Rule("r1", "d", ["治疗"])])
        p.seal()
        m1 = p.md5
        p.rules.append(Rule("r2", "d2", ["根治"]))
        assert p.compute_md5() != m1
        assert not p.verify_md5()  # 内容变了 md5 未重封 → 校验失败（防篡改）

    def test_sign_records_signer(self):
        p = RulePack("rp", "0.1.0", "G1_compliance", rules=[Rule("r1", "d", ["治疗"])])
        assert p.is_signed is False
        p.sign("合规负责人", "2026-07-05T10:00:00Z")
        assert p.is_signed is True
        assert p.signed_by == "合规负责人"

    def test_mock_pack_not_production_ready(self):
        """严禁 20：mock 规则即使签收也不算生产可用。"""
        p = RulePack("rp", "0.1.0", "G1", rules=[Rule("r1", "d", ["x"])], is_mock=True)
        p.sign("someone", "t")
        assert p.is_signed is True
        assert p.is_production_ready is False  # is_mock=True → 非生产

    def test_unsigned_not_production_ready(self):
        p = RulePack("rp", "0.1.0", "G1", rules=[Rule("r1", "d", ["x"])], is_mock=False)
        p.seal()
        assert p.is_production_ready is False  # 未签收 → 非生产


# ──────────────────────────────────────────────────────────────────────
# G1-G6 外置规则集
# ──────────────────────────────────────────────────────────────────────
class TestGateRulepacks:
    def test_six_packs_present(self):
        packs = all_gate_rulepacks()
        assert set(packs) == {
            "G1_compliance", "G2_state_boundary", "G3_fact_ref",
            "G4_platform_structure", "G5_brand_consistency", "G6_format_complete"}

    def test_all_sealed_and_mock(self):
        for p in all_gate_rulepacks().values():
            assert p.verify_md5()          # 已封 md5
            assert p.is_mock is True       # 骨架期
            assert p.is_production_ready is False
            assert p.changelog             # 有变更记录

    def test_g1_has_caution_conditional_rule(self):
        g1 = all_gate_rulepacks()["G1_compliance"]
        caution = [r for r in g1.rules if r.action == RuleAction.CONDITIONAL_PASS]
        assert caution and "修护" in caution[0].keywords


# ──────────────────────────────────────────────────────────────────────
# G3 正式 FactRefAdjudicator 契约
# ──────────────────────────────────────────────────────────────────────
class TestG3FormalContract:
    def test_unsourced_claim_fails(self):
        adj = MockFormalG3Adjudicator()
        res = adj.adjudicate_claims([FactClaim(fact_claim="有效率99%", source_ref=None)])
        assert res.passed is False
        assert "有效率99%" in res.violations

    def test_detection_missing_institution_fails(self):
        adj = MockFormalG3Adjudicator()
        claim = FactClaim(
            fact_claim="体外法检测报告编号XYJCR241029-005",
            source_ref="dfd_fact_002",
            evidence_type=EvidenceType.DETECTION_REPORT,
            detection_method="体外法", report_no="XYJCR241029-005",
            institution=None,  # 缺机构
        )
        res = adj.adjudicate_claims([claim])
        assert res.passed is False
        assert any("检测机构" in v.reason for v in res.claim_verdicts)

    def test_complete_detection_passes(self):
        adj = MockFormalG3Adjudicator()
        claim = FactClaim(
            fact_claim="体外法检测报告", source_ref="dfd_fact_002",
            evidence_type=EvidenceType.DETECTION_REPORT,
            detection_method="体外法", report_no="XYJCR241029-005",
            institution="广东欣研检验检测有限公司",
        )
        assert adj.adjudicate_claims([claim]).passed is True

    def test_fail_closed_default(self):
        assert FactClaim(fact_claim="x").fail_closed is True


# ──────────────────────────────────────────────────────────────────────
# G4 四平台规则集契约
# ──────────────────────────────────────────────────────────────────────
class TestPlatformContract:
    def test_four_platforms(self):
        rs = platform_rulesets()
        assert set(rs) == set(VALID_PLATFORMS)

    def test_xiaohongshu_required_sections(self):
        rs = platform_rulesets()["xiaohongshu"]
        assert set(rs.required_sections) == {"标题", "正文", "标签"}

    def test_all_mock(self):
        assert all(p.is_mock for p in platform_rulesets().values())


# ──────────────────────────────────────────────────────────────────────
# 观测接口 Protocol + Mock
# ──────────────────────────────────────────────────────────────────────
class TestObsContracts:
    def test_mock_report_store_memory(self):
        store = MockReportStore()
        obs = ProductionLineObserver()
        rep = build_daily_report(obs, day="2026-07-05")
        sid = store.save_report(rep)
        assert sid.startswith("mock_report_")
        assert store.get_report("2026-07-05") is rep
        assert store.list_dates() == ["2026-07-05"]
        assert store.is_mock is True

    def test_mock_scheduler_registers_not_runs(self):
        sch = MockScheduler()
        sch.register(ScheduledJob("daily", "0 9 * * *", "每日日报"))
        assert len(sch.list_jobs()) == 1
        assert sch.is_mock is True

    def test_mock_alert_sink_collects(self):
        sink = MockAlertSink()
        sink.emit(AlertLevel.HIGH, "no_recall_client", "存在无召回客户端运行")
        drained = sink.drain()
        assert drained[0]["level"] == "high"
        assert sink.drain() == []  # drain 后清空


# ──────────────────────────────────────────────────────────────────────
# feature flags 全默认 False
# ──────────────────────────────────────────────────────────────────────
class TestFeatureFlags:
    def test_all_default_false(self):
        f = FeatureFlags()
        assert f.any_enabled() is False
        for k, v in f.as_dict().items():
            assert v is False, f"{k} 默认应为 False"

    def test_default_flags_instance_all_false(self):
        assert DEFAULT_FLAGS.any_enabled() is False

    def test_critical_flags_present(self):
        keys = FeatureFlags().as_dict().keys()
        for k in ["M1_ENABLED", "CONTENT_GENERATE_ENABLED", "REAL_9080_ENABLED",
                  "REAL_MODEL_ENABLED", "APPROVED_WRITE_ENABLED", "PUBLISH_ENABLED",
                  "REAL_OBSERVABILITY_ENABLED"]:
            assert k in keys


# ──────────────────────────────────────────────────────────────────────
# 联调准备清单
# ──────────────────────────────────────────────────────────────────────
class TestReadinessChecklists:
    def test_five_checklists_present(self):
        c = default_checklists()
        assert c.env_var and c.service_dependency and c.rollback and c.red_line and c.smoke_test

    def test_not_ready_in_skeleton(self):
        c = default_checklists()
        assert c.is_ready is False  # 骨架期全未勾
        assert all(not i.done for i in c.all_items())

    def test_red_line_checklist_covers_bans(self):
        c = default_checklists()
        keys = {i.key for i in c.red_line}
        assert {"rl_no_content_generate", "rl_no_approved_write", "rl_no_9200",
                "rl_no_reindex", "rl_no_site_published", "rl_no_publish_pool"} <= keys

    def test_9200_unreachable_is_blocking(self):
        c = default_checklists()
        dep = {i.key: i for i in c.service_dependency}
        assert dep["dep_9200_unreachable"].blocking is True


# ──────────────────────────────────────────────────────────────────────
# Qoder 补强测试
# ──────────────────────────────────────────────────────────────────────


class TestRulePackTamperDetection:
    """rulepack 防篡改：规则变动后 verify_md5 应失败。"""

    def test_keyword_change_invalidates_md5(self):
        p = RulePack("rp", "0.1.0", "G1", rules=[Rule("r1", "d", ["治疗"])])
        p.seal()
        assert p.verify_md5()
        # 修改关键词 → md5 应失效
        p.rules[0].keywords.append("治愈")
        assert not p.verify_md5()


class TestG3FailClosedComplete:
    """G3 正式契约 fail_closed 完整覆盖：无源 + 检测三要素任意缺失。"""

    def test_detection_missing_report_no_fails(self):
        adj = MockFormalG3Adjudicator()
        claim = FactClaim(
            fact_claim="体外法检测", source_ref="ref_001",
            evidence_type=EvidenceType.DETECTION_REPORT,
            detection_method="体外法", report_no=None,  # 缺报告编号
            institution="广东欣研",
        )
        res = adj.adjudicate_claims([claim])
        assert res.passed is False
        assert any("报告编号" in v.reason for v in res.claim_verdicts)


class TestFeatureFlagsAnyEnabledFixed:
    """any_enabled 应正确反映非全 False 状态（Qoder 修补）。"""

    def test_any_enabled_when_one_flag_true(self):
        f = FeatureFlags(M1_ENABLED=True)
        assert f.any_enabled() is True  # 修补前恒 False

    def test_all_false_still_returns_false(self):
        f = FeatureFlags()
        assert f.any_enabled() is False


class TestReadinessReadyWhenAllDone:
    """is_ready 应在全部阻塞项完成后返回 True。"""

    def test_ready_when_all_blocking_done(self):
        c = default_checklists()
        for item in c.all_items():
            item.done = True
        assert c.is_ready is True
