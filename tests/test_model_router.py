"""模型路由与兜底层测试 — 红线测试 + 单元测试 + 正反样例。

覆盖《模型路由与兜底层设计 V0.1》：
- 2.2 任务路由映射
- 5.1/5.2 Fallback 触发与纪律
- 硬边界一：fallback 输出过同一套门，标准不降级
- 硬边界二：used_materials 为空 → 只出缺料报告
- 硬边界三：免费/低成本模型不得接触敏感数据
- 硬边界四：熔断（不自动恢复，人工解除，排队不丢弃）
- 第六章：调用日志 14 字段 + 成本汇总
"""
import pytest

from backend.app.model_router import (
    CallLog,
    CircuitBreaker,
    DraftTask,
    GateResult,
    MissingMaterialReport,
    MockModelClient,
    ModelReply,
    ModelRole,
    ModelRouter,
    ModelRouterConfig,
    RouterResult,
    TaskStatus,
    TaskType,
)
from backend.app.model_router.call_log import REQUIRED_FIELDS
from backend.app.model_router.circuit_breaker import CircuitOpenError
from backend.app.model_router.prescan import prescan_g1
from backend.app.model_router.router import RESTRICTED_EXPANSION_RULES, build_prompt
from backend.app.model_router.sensitive_guard import scan_sensitive


MATERIALS = [
    {"id": "dfd_fact_001", "content": "润养安肤奢华油为普通化妆品，舒缓报告编号XYJCR241029-005。"},
    {"id": "dfd_fact_002", "content": "检测方法为体外法（透明质酸酶抑制法）。"},
]


def make_router(**overrides):
    """标准四角色 mock 路由器。"""
    cfg = ModelRouterConfig.default()
    clients = {
        ModelRole.PRIMARY: MockModelClient(model_name="mock-primary"),
        ModelRole.FALLBACK: MockModelClient(model_name="mock-fallback"),
        ModelRole.REVIEW: MockModelClient(model_name="mock-review"),
        ModelRole.REWRITE: MockModelClient(model_name="mock-rewrite"),
    }
    clients.update(overrides.pop("clients", {}))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return ModelRouter(config=cfg, clients=clients)


def task(task_type=TaskType.FACT_STRICT, materials=MATERIALS, content_id="content_t1", **kw):
    return DraftTask(content_id=content_id, task_type=task_type,
                     brief="写一篇奢华油品牌科普", used_materials=materials, **kw)


# ──────────────────────────────────────────────────────────────────────
# 正样例：正常出稿
# ──────────────────────────────────────────────────────────────────────
class TestHappyPath:
    def test_fact_strict_routes_to_primary(self):
        r = make_router()
        res = r.generate_draft(task())
        assert isinstance(res, RouterResult)
        assert res.status == TaskStatus.DRAFT_CANDIDATE
        assert res.produced_by_role == ModelRole.PRIMARY
        assert res.produced_by_model == "mock-primary"

    def test_platform_rewrite_routes_to_rewrite(self):
        r = make_router()
        res = r.generate_draft(task(TaskType.PLATFORM_REWRITE, platform="xiaohongshu"))
        assert res.produced_by_role == ModelRole.REWRITE

    def test_output_binds_used_materials_ids(self):
        """硬边界二（正向）：每份输出必须附带素材 ID 列表。"""
        r = make_router()
        res = r.generate_draft(task())
        assert res.used_materials_ids == ["dfd_fact_001", "dfd_fact_002"]

    def test_publish_allowed_is_constant_false(self):
        """M1 严禁项：不自动发布/不写 approved，字段为常量、无写入口。"""
        r = make_router()
        res = r.generate_draft(task())
        assert res.publish_allowed is False
        assert res.writes_approved is False
        with pytest.raises(TypeError):
            RouterResult(content_id="x", status=TaskStatus.DRAFT_CANDIDATE,
                         task_type=TaskType.FACT_STRICT, publish_allowed=True)

    def test_state_aesthetic_gets_rewrite_polish(self):
        r = make_router()
        res = r.generate_draft(task(TaskType.STATE_AESTHETIC))
        rewrite_calls = r.clients[ModelRole.REWRITE].calls
        assert len(rewrite_calls) == 1 and "不得新增事实" in rewrite_calls[0]
        assert res.status == TaskStatus.DRAFT_CANDIDATE

    def test_high_risk_double_check_and_must_sign(self):
        """高风险内容：review_model 双检 + must_sign，必须人审。"""
        r = make_router()
        res = r.generate_draft(task(TaskType.HIGH_RISK))
        assert len(r.clients[ModelRole.REVIEW].calls) == 1
        assert res.must_sign is True
        assert any(g.gate == "review_model_precheck" for g in res.gate_results)

    def test_restricted_expansion_prompt_for_kimi_candidates(self):
        """Kimi 受限扩写：只吃 used_materials，不补事实（提示词侧钉死）。"""
        p = build_prompt(task(TaskType.LONG_EXPANSION))
        assert RESTRICTED_EXPANSION_RULES in p
        assert "不得新增任何事实" in p


# ──────────────────────────────────────────────────────────────────────
# 硬边界二：缺料报告
# ──────────────────────────────────────────────────────────────────────
class TestMissingMaterials:
    def test_empty_materials_yields_report_not_candidate(self):
        r = make_router()
        res = r.generate_draft(task(materials=[]))
        assert isinstance(res, MissingMaterialReport)
        assert res.status == TaskStatus.MISSING_MATERIALS
        assert res.enters_gates is False
        assert res.enters_candidate_review is False
        assert res.missing_material_types and res.suggested_recall_keywords

    def test_no_model_called_when_materials_empty(self):
        """缺料时不许硬编——模型一次都不能调。"""
        r = make_router()
        r.generate_draft(task(materials=[]))
        assert all(len(c.calls) == 0 for c in r.clients.values())
        assert r.call_log.entries == []


# ──────────────────────────────────────────────────────────────────────
# Fallback 触发与纪律（5.1 / 5.2）
# ──────────────────────────────────────────────────────────────────────
class TestFallback:
    def test_primary_timeout_switches_to_fallback(self):
        r = make_router(clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", fail_times=1),
        })
        res = r.generate_draft(task())
        assert res.status == TaskStatus.DRAFT_CANDIDATE
        assert res.produced_by_role == ModelRole.FALLBACK

    def test_quality_fail_retries_then_fallback(self):
        """质量不达标：同模型打回重试 ≤2 次，仍不达标切 fallback。"""
        bad = ModelReply(text="普通草稿", quality_score=10.0)
        r = make_router(clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", scripted_replies=[bad]),
        })
        res = r.generate_draft(task())
        assert len(r.clients[ModelRole.PRIMARY].calls) == 3  # 1 次 + 2 次重试
        assert res.produced_by_role == ModelRole.FALLBACK

    def test_banned_word_no_retry_same_model(self):
        """G1 预扫描命中禁用词：直接打回，不重试同模型。"""
        banned = ModelReply(text="本品可根治敏感肌，100%有效")
        r = make_router(clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", scripted_replies=[banned]),
        })
        res = r.generate_draft(task())
        assert len(r.clients[ModelRole.PRIMARY].calls) == 1  # 零重试
        assert res.produced_by_role == ModelRole.FALLBACK

    def test_double_failure_trips_stop_manual_review(self):
        """主模型+fallback 双失败 ≥1 次 → stop，进入 manual_review。"""
        r = make_router(clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", fail_times=9),
            ModelRole.FALLBACK: MockModelClient(model_name="mock-fallback", fail_times=9),
        })
        res = r.generate_draft(task())
        assert res.status == TaskStatus.MANUAL_REVIEW
        assert r.breaker.state == "stop"

    def test_fallback_output_passes_same_gates(self):
        """硬边界一：fallback 输出执行与 primary 完全相同的门扫描。"""
        seen = []

        def pipeline(text, t):
            seen.append(text)
            return [GateResult(gate="G2_mock", passed=True)]

        r = make_router(clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", fail_times=1),
        })
        r.gate_pipeline = pipeline
        res = r.generate_draft(task())
        assert res.produced_by_role == ModelRole.FALLBACK
        assert seen == [res.text]  # fallback 稿照样进 pipeline
        gates = {g.gate for g in res.gate_results}
        assert {"G1_prescan", "G2_mock"} <= gates


# ──────────────────────────────────────────────────────────────────────
# 硬边界三：敏感数据隔离
# ──────────────────────────────────────────────────────────────────────
class TestSensitiveGuard:
    def test_scan_detects_credentials_privacy_raw_business(self):
        assert scan_sensitive("api_key: sk-abcdefgh12345678xx")
        assert scan_sensitive("客户手机 13812345678")
        assert scan_sensitive("给王女士13812345678写回访")  # 号码紧贴中文也必须命中
        assert scan_sensitive("这是真实经营数据，勿外传")
        assert scan_sensitive("店名已脱敏为 store_001，数据标注 reference_only") == []

    def test_low_cost_model_blocked_on_sensitive_data(self):
        """低成本改写模型收到含手机号的任务 → 拦截，不发起调用。"""
        r = make_router()
        res = r.generate_draft(task(
            TaskType.PLATFORM_REWRITE,
            content_id="content_sensitive",
        ))
        assert res.status == TaskStatus.DRAFT_CANDIDATE  # 干净任务正常走

        dirty = DraftTask(
            content_id="content_dirty", task_type=TaskType.PLATFORM_REWRITE,
            brief="给客户王女士 13812345678 写回访文案",
            used_materials=MATERIALS,
        )
        res2 = r.generate_draft(dirty)
        assert res2.status == TaskStatus.BLOCKED_SENSITIVE
        # 拦截发生在调用前：rewrite 模型没有收到任何 prompt
        assert all("13812345678" not in p for p in r.clients[ModelRole.REWRITE].calls)
        blocked = [e for e in r.call_log.entries if e.content_id == "content_dirty"]
        assert blocked and blocked[0].success is False
        assert "sensitive_data" in blocked[0].fail_reason

    def test_primary_not_low_cost_allows_task(self):
        """主模型非低成本位，不触发免费模型敏感拦截（仍受上游脱敏纪律约束）。"""
        r = make_router()
        res = r.generate_draft(DraftTask(
            content_id="c", task_type=TaskType.FACT_STRICT,
            brief="围绕检测报告写科普", used_materials=MATERIALS,
        ))
        assert res.status == TaskStatus.DRAFT_CANDIDATE


# ──────────────────────────────────────────────────────────────────────
# 硬边界四：熔断
# ──────────────────────────────────────────────────────────────────────
class TestCircuitBreaker:
    def test_primary_streak_trips_hold(self):
        b = CircuitBreaker()
        b.on_primary_failure(); b.on_primary_failure()
        assert b.state == "closed"
        b.on_primary_failure()
        assert b.state == "hold"

    def test_open_breaker_queues_tasks_not_drops(self):
        r = make_router()
        r.breaker._trip("hold", "test")
        res = r.generate_draft(task(content_id="queued_1"))
        assert res.status == TaskStatus.HELD
        assert r.breaker.queued_tasks == ["queued_1"]

    def test_no_auto_recovery_release_requires_operator(self):
        b = CircuitBreaker()
        b._trip("stop", "双失败")
        assert b.is_open
        with pytest.raises(ValueError):
            b.release("", "")
        queued = b.release("吴哥", "人工核查后确认恢复")
        assert b.state == "closed"
        assert b.trip_history[-1].released_by == "吴哥"
        assert isinstance(queued, list)

    def test_g1_fail_streak_same_content_trips_stop(self):
        b = CircuitBreaker()
        for _ in range(3):
            b.on_g1_fail("content_x")
        assert b.state == "stop"

    def test_max_calls_per_content_trips_stop(self):
        bad = ModelReply(text="普通草稿", quality_score=10.0)
        r = make_router(max_calls_per_content=2, clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", scripted_replies=[bad]),
            ModelRole.FALLBACK: MockModelClient(model_name="mock-fallback", scripted_replies=[bad]),
        })
        res = r.generate_draft(task())
        assert r.breaker.state == "stop"
        assert res.status == TaskStatus.MANUAL_REVIEW
        assert r.call_log.calls_for_content("content_t1") <= 2

    def test_daily_cost_over_limit_trips_stop(self):
        r = make_router(daily_cost_limit=0.0001)
        r.config.roles[ModelRole.PRIMARY].cost_per_1k_tokens = 100.0
        r.generate_draft(task())
        assert r.breaker.state == "stop"
        assert "成本" in r.breaker.trip_history[-1].reason


# ──────────────────────────────────────────────────────────────────────
# 调用日志与成本（第六章）
# ──────────────────────────────────────────────────────────────────────
class TestCallLog:
    def test_all_required_fields_present(self):
        r = make_router()
        r.generate_draft(task())
        entry = r.call_log.entries[0]
        for f in REQUIRED_FIELDS:
            assert hasattr(entry, f), f"缺少必记字段 {f}"

    def test_free_model_zero_cost_but_recorded(self):
        """免费模型不计成本但仍记录次数和失败率。"""
        log = CallLog()
        log.record(model_role=ModelRole.REWRITE, provider="mock", model_name="free-model",
                   input_tokens=1000, output_tokens=1000, cost_per_1k_tokens=0.0,
                   latency_ms=5, success=False, fail_reason="timeout",
                   content_id="c1", used_materials_ids=[], g1_result=None)
        stats = log.stats_by_model()["free-model"]
        assert stats["cost"] == 0.0
        assert stats["calls"] == 1 and stats["fail_rate"] == 1.0

    def test_cost_computed_from_tokens(self):
        log = CallLog()
        e = log.record(model_role=ModelRole.PRIMARY, provider="mock", model_name="m",
                       input_tokens=500, output_tokens=500, cost_per_1k_tokens=2.0,
                       latency_ms=5, success=True, fail_reason=None,
                       content_id="c1", used_materials_ids=["a"], g1_result="pass")
        assert e.cost == 2.0
        assert log.daily_cost_total() == 2.0

    def test_every_call_logged_including_failures(self):
        r = make_router(clients={
            ModelRole.PRIMARY: MockModelClient(model_name="mock-primary", fail_times=1),
        })
        r.generate_draft(task())
        assert len(r.call_log.entries) == 2  # 1 失败 + 1 fallback 成功
        assert r.call_log.entries[0].success is False
        assert r.call_log.entries[0].fail_reason == "timeout"


# ──────────────────────────────────────────────────────────────────────
# G1 预扫描词表（正反样例）
# ──────────────────────────────────────────────────────────────────────
class TestPrescan:
    @pytest.mark.parametrize("bad", [
        "本品可根治敏感肌", "治疗痘痘一绝", "100%有效", "永久祛斑",
        "全球第一精华油", "用了就转运", "旺财好物", "医疗级修护", "药妆天花板",
        "立竿见影的特效", "加盟保证赚钱",
    ])
    def test_banned_samples_hit(self, bad):
        assert prescan_g1(bad), f"反样例未命中: {bad}"

    @pytest.mark.parametrize("good", [
        "有助于舒缓肌肤状态，帮助改善肌肤干燥",
        "老客势能还在，只是没被接住",
        "皮肤的状态，是你内在节奏的镜像",
        "有助于修护肌肤状态（依据体外检测报告）",
        "不是修护，是帮你的皮肤找回自己的节奏",
    ])
    def test_allowed_samples_pass(self, good):
        assert prescan_g1(good) == [], f"正样例被误杀: {good}"


# ──────────────────────────────────────────────────────────────────────
# 配置装载（第四章）
# ──────────────────────────────────────────────────────────────────────
class TestConfig:
    def test_default_has_four_roles_provider_tbd(self):
        cfg = ModelRouterConfig.default()
        assert set(cfg.roles) == set(ModelRole)
        assert all(rc.provider == "待定" for rc in cfg.roles.values())

    def test_from_dict_matches_design_json(self):
        cfg = ModelRouterConfig.from_dict({
            "model_router": {
                "primary": {"provider": "p1", "model": "m1", "timeout_seconds": 30},
                "fallback": {"max_retries": 2, "trigger_on": ["timeout", "quality_fail", "style_drift"]},
                "rewrite": {"batch_mode": True, "is_low_cost": True},
                "quality_threshold": 70,
            }
        })
        assert cfg.roles[ModelRole.PRIMARY].provider == "p1"
        assert cfg.roles[ModelRole.FALLBACK].max_retries == 2
        assert cfg.roles[ModelRole.REWRITE].batch_mode is True
        assert cfg.quality_threshold == 70
