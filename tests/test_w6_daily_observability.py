"""W6 测试 — 产线日报与运行观测骨架。

覆盖 M1-W6 条件施工许可 五·指标 + 六·异常观测：
- brief/draft_candidate/gate_blocked/missing_materials/needs_human_review/
  marked_ready_to_publish/rejected_for_revision 计数
- 异常：无 recall_client / 过滤后缺料 / G1-G3 高发 / loop 耗尽 / 人审积压
- mock 日报输出结构
- marked_ready 不当发布量、candidate_review 不当 approved
- 无真实库/监控/发布/9080/FastAPI
"""
import pytest

from backend.app.content_factory import Brief, ContentFactory, FactoryTaskState
from backend.app.content_factory.drafting import DraftGenerator
from backend.app.content_factory.gates import GatePipeline
from backend.app.content_factory.midplatform import MidPlatformMock
from backend.app.content_factory.observability import (
    AnomalyKind, AnomalyThresholds, DailyReport, ProductionLineObserver,
    RunObservation, RunOutcome, build_daily_report,
)
from backend.app.content_factory.recall import MockRecallClient, RecallResult, RecallStatus
from backend.app.model_router import (
    MockModelClient, ModelReply, ModelRole, ModelRouter, ModelRouterConfig,
)


def mat(id, content):
    return {"id": id, "content": content, "material_type": "fact_card",
            "source_type": "9080_approved", "status": "active"}


CLEAN_XHS = ("标题：奢华油的日常。正文：润养安肤奢华油为普通化妆品，"
             "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司。标签：护肤。")
CLEAN_MATERIALS = [
    mat("dfd_fact_001", "润养安肤奢华油为普通化妆品"),
    mat("dfd_fact_002", "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司"),
]
# 稿件句句可溯源（过 W3），但检测宣称缺"机构"要素 → W4 G3 检测完整性 fail
# （注意：G3 的"无源事实句"检查与 W3 sentence-audit 重叠，会先在 W3 拦截；
#  真正只在 W4 触发的 G3 fail 是"检测三要素不全"这条。）
G3_DETECTION_FAIL = ("标题：油。正文：润养安肤奢华油为普通化妆品，"
                     "体外法检测报告编号XYJCR241029-005。标签：护肤。")


def make_factory(reply_text, materials, with_recall=True, with_pipeline=True):
    cfg = ModelRouterConfig.default()
    cl = {r: MockModelClient(model_name=f"m-{r.value}", scripted_replies=[ModelReply(text=reply_text)])
          for r in ModelRole}
    router = ModelRouter(config=cfg, clients=cl)
    client = (MockRecallClient(scripted_results=[RecallResult(materials=list(materials), status=RecallStatus.APPROVED)])
              if with_recall else None)
    return ContentFactory(recall_client=client, draft_generator=DraftGenerator(router=router),
                          gate_pipeline=GatePipeline() if with_pipeline else None)


def run(reply, materials, platform="xiaohongshu", **kw):
    f = make_factory(reply, materials, **kw)
    return f.process_brief(Brief(raw_text="奢华油科普", target_platform=platform))


# ──────────────────────────────────────────────────────────────────────
# 观测切片
# ──────────────────────────────────────────────────────────────────────
class TestRunObservation:
    def test_packaged_outcome(self):
        obs = RunObservation.from_factory_result(run(CLEAN_XHS, CLEAN_MATERIALS))
        assert obs.outcome == RunOutcome.PACKAGED
        assert obs.had_recall_client is True

    def test_missing_outcome(self):
        obs = RunObservation.from_factory_result(run(CLEAN_XHS, []))
        assert obs.outcome == RunOutcome.HALTED_MISSING_MATERIALS

    def test_no_recall_client_flagged(self):
        r = run(CLEAN_XHS, CLEAN_MATERIALS, with_recall=False)
        obs = RunObservation.from_factory_result(r)
        assert obs.outcome == RunOutcome.HALTED_MISSING_MATERIALS
        assert obs.had_recall_client is False

    def test_gate_blocked_outcome_with_gate_stats(self):
        # 串品牌 → GATE_BLOCKED；G5 fail（非 G1/G3）
        r = run("标题：油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。", CLEAN_MATERIALS)
        obs = RunObservation.from_factory_result(r)
        assert obs.outcome == RunOutcome.GATE_BLOCKED
        assert obs.g1_fail_count == 0 and obs.g3_fail_count == 0

    def test_g3_fail_counted(self):
        # 检测宣称缺"机构" → W4 G3 检测完整性 fail（过 W3、在 W4 被拦）
        r = run(G3_DETECTION_FAIL, CLEAN_MATERIALS)
        obs = RunObservation.from_factory_result(r)
        assert obs.outcome == RunOutcome.GATE_BLOCKED
        assert obs.g3_fail_count >= 1


# ──────────────────────────────────────────────────────────────────────
# 指标聚合（许可五）
# ──────────────────────────────────────────────────────────────────────
class TestMetrics:
    def test_core_counts(self):
        obs = ProductionLineObserver()
        obs.observe(run(CLEAN_XHS, CLEAN_MATERIALS))                                   # packaged
        obs.observe(run(CLEAN_XHS, []))                                                # missing
        obs.observe(run("标题：油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。", CLEAN_MATERIALS))  # gate_blocked
        obs.observe(run("本品有效率高达98%。润养安肤奢华油为普通化妆品。", CLEAN_MATERIALS))  # blocked_draft(新增事实)
        rep = build_daily_report(obs, day="2026-07-05")
        m = rep.metrics
        assert m["run_count"] == 4
        assert m["draft_candidate_count"] == 1
        assert m["missing_materials_count"] == 1
        assert m["gate_blocked_count"] == 1
        assert m["draft_blocked_count"] == 1

    def test_review_state_metrics_from_queue(self):
        # 用中台队列产生 marked_ready / rejected / needs_human
        mp = MidPlatformMock()
        mp.ingest_factory_result(run(CLEAN_XHS, CLEAN_MATERIALS))  # ready
        cond = CLEAN_XHS.replace("为普通化妆品", "为普通化妆品，有助于修护肌肤状态")
        e2 = mp.ingest_factory_result(run(cond, CLEAN_MATERIALS))  # needs_human
        # 备发一条
        entries = mp.queue.list_all()
        ready = [x for x in entries if x.state.value == "ready_for_review"][0]
        mp.action_mark_ready(ready.content_id, "小编")

        obs = ProductionLineObserver()
        obs.snapshot_review_queue(mp.queue)
        rep = build_daily_report(obs)
        assert rep.metrics["marked_ready_to_publish_count"] == 1
        assert rep.metrics["needs_human_review_count"] == 1

    def test_no_publish_no_approved_metric_names(self):
        obs = ProductionLineObserver()
        rep = build_daily_report(obs)
        # 日报不产出任何"发布量/入库量/approved"口径
        assert "published_count" not in rep.metrics
        assert "approved_count" not in rep.metrics
        assert "site_published_count" not in rep.metrics
        # marked_ready 存在但语义为"备发标记"
        assert "marked_ready_to_publish_count" in rep.metrics


# ──────────────────────────────────────────────────────────────────────
# 异常观测（许可六）
# ──────────────────────────────────────────────────────────────────────
class TestAnomalies:
    def _kinds(self, rep):
        return {a.kind for a in rep.anomalies}

    def test_no_recall_client_anomaly(self):
        obs = ProductionLineObserver()
        obs.observe(run(CLEAN_XHS, CLEAN_MATERIALS, with_recall=False))
        rep = build_daily_report(obs)
        assert AnomalyKind.NO_RECALL_CLIENT in self._kinds(rep)

    def test_missing_after_filter_anomaly(self):
        obs = ProductionLineObserver()
        obs.observe(run(CLEAN_XHS, []))  # 有 recall client 但召回为空 → 过滤后缺料
        rep = build_daily_report(obs)
        assert AnomalyKind.MISSING_AFTER_FILTER in self._kinds(rep)

    def test_high_g1_g3_fail_anomaly(self):
        obs = ProductionLineObserver()
        # 全部过门运行都 G3 检测完整性 fail → 高发
        for _ in range(3):
            obs.observe(run(G3_DETECTION_FAIL, CLEAN_MATERIALS))
        rep = build_daily_report(obs)
        assert AnomalyKind.HIGH_G1_G3_FAIL in self._kinds(rep)

    def test_loop_exhausted_anomaly(self):
        # 用 gate pipeline + revise 永不修好构造 loop 耗尽
        cfg = ModelRouterConfig.default()
        cl = {r: MockModelClient(model_name=f"m-{r.value}", scripted_replies=[ModelReply(text="标题。正文。")])
              for r in ModelRole}
        # 缺"标签" → G4 fail（非红线，可 loop）；revise 永不修 → 3 圈耗尽
        pipe = GatePipeline(revise_callback=lambda v, r: v)
        client = MockRecallClient(scripted_results=[RecallResult(materials=list(CLEAN_MATERIALS), status=RecallStatus.APPROVED)])
        f = ContentFactory(recall_client=client,
                           draft_generator=DraftGenerator(router=ModelRouter(config=cfg, clients=cl)),
                           gate_pipeline=pipe)
        r = f.process_brief(Brief(raw_text="x", target_platform="xiaohongshu"))
        obs = ProductionLineObserver()
        obs.observe(r)
        rep = build_daily_report(obs)
        assert AnomalyKind.LOOP_EXHAUSTED in self._kinds(rep)

    def test_human_review_backlog_anomaly(self):
        obs = ProductionLineObserver()
        obs.review_state_counts = {"needs_human_review": 4, "must_sign": 2}  # 合计 6 ≥ 阈值 5
        rep = build_daily_report(obs)
        assert AnomalyKind.HUMAN_REVIEW_BACKLOG in self._kinds(rep)

    def test_clean_run_no_anomaly(self):
        obs = ProductionLineObserver()
        obs.observe(run(CLEAN_XHS, CLEAN_MATERIALS))  # 干净 packaged
        rep = build_daily_report(obs)
        assert rep.anomalies == []


# ──────────────────────────────────────────────────────────────────────
# 日报输出结构
# ──────────────────────────────────────────────────────────────────────
class TestDailyReportOutput:
    def test_to_dict_structure(self):
        obs = ProductionLineObserver()
        obs.observe(run(CLEAN_XHS, CLEAN_MATERIALS))
        d = build_daily_report(obs, day="2026-07-05").to_dict()
        assert d["date"] == "2026-07-05"
        assert set(d.keys()) == {"date", "metrics", "by_outcome", "review_state_counts", "anomalies"}
        assert isinstance(d["metrics"], dict)

    def test_thresholds_configurable(self):
        obs = ProductionLineObserver()
        obs.review_state_counts = {"needs_human_review": 3}
        # 默认阈值 5 → 不报；调低到 3 → 报
        assert build_daily_report(obs).anomalies == []
        rep = build_daily_report(obs, thresholds=AnomalyThresholds(human_backlog=3))
        assert any(a.kind == AnomalyKind.HUMAN_REVIEW_BACKLOG for a in rep.anomalies)


# ──────────────────────────────────────────────────────────────────────
# 无副作用：观测只读，不改 factory 结果、不写库
# ──────────────────────────────────────────────────────────────────────
class TestReadOnly:
    def test_observe_does_not_mutate_result(self):
        r = run(CLEAN_XHS, CLEAN_MATERIALS)
        before_state = r.state
        ProductionLineObserver().observe(r)
        assert r.state == before_state  # 观测不改动 result


# ──────────────────────────────────────────────────────────────────────
# Qoder 补强测试
# ──────────────────────────────────────────────────────────────────────


class TestBriefCountDedup:
    """brief_count 以 brief_id 去重计数。"""

    def test_same_brief_observed_twice_counts_once(self):
        obs = ProductionLineObserver()
        # 直接构造同 brief_id 的观测切片（factory 每次生成 UUID，故绕过 factory）
        obs.observations.append(RunObservation(
            content_id="c1", brief_id="brief_dup", trace_id="t1", outcome=RunOutcome.PACKAGED))
        obs.observations.append(RunObservation(
            content_id="c2", brief_id="brief_dup", trace_id="t2", outcome=RunOutcome.PACKAGED))
        assert obs.brief_count == 1
        assert obs.run_count == 2  # run_count 不去重


class TestG1G3FailRateDenominator:
    """G1/G3 fail 高发按"过门运行"比例计算，非全部运行。"""

    def test_g1g3_rate_only_counts_gated_runs(self):
        obs = ProductionLineObserver()
        # 2 次干净 packaged（过门、G1/G3 pass）
        obs.observe(run(CLEAN_XHS, CLEAN_MATERIALS))
        obs.observe(run(CLEAN_XHS, CLEAN_MATERIALS))
        # 1 次 G3 检测完整性 fail（过门）
        obs.observe(run(G3_DETECTION_FAIL, CLEAN_MATERIALS))
        # 1 次缺料停单（不过门，loop_rounds_used=0）
        obs.observe(run(CLEAN_XHS, []))
        rep = build_daily_report(obs)
        # 过门运行 3 次，其中 1 次 G3 fail → 1/3 ≈ 0.33 ≥ 0.30 → 触发
        kinds = {a.kind for a in rep.anomalies}
        assert AnomalyKind.HIGH_G1_G3_FAIL in kinds


class TestDraftVsGateBlockedIndependence:
    """draft_blocked_count 与 gate_blocked_count 独立计数，不重复。"""

    def test_draft_and_gate_blocked_counted_separately(self):
        obs = ProductionLineObserver()
        # W3 草稿拦截（无源事实句）
        obs.observe(run("临床数据显示99%有效率。无源事实句。", CLEAN_MATERIALS))
        # W4 门检拦截（串品牌）
        obs.observe(run("标题：油。正文：润养安肤奢华油为普通化妆品，对比雅诗兰黛更好。标签：护肤。", CLEAN_MATERIALS))
        rep = build_daily_report(obs)
        assert rep.metrics["draft_blocked_count"] == 1
        assert rep.metrics["gate_blocked_count"] == 1
        assert rep.metrics["draft_candidate_count"] == 0
