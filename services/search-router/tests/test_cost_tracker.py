"""测试 CostTracker 五级熔断 + 临时 SQLite + 自动恢复（T2B）。

SQLite 一律使用临时目录 / 临时库（tmp_path 或 :memory:），不写生产路径。
时间判断通过注入 now（datetime）完成，测试不 sleep 真实时间。
不联网、不真实调用 Provider、不发真实通知。
"""

import os
from datetime import datetime, timedelta

import pytest

from search_router.config import SearchRouterConfig
from search_router.cost_tracker import CostTracker
from search_router.models.cost_record import CircuitState, PauseReason
from search_router.models.search_response import ErrorCode


NOW = datetime(2026, 6, 27, 10, 0, 0)


@pytest.fixture
def tracker(tmp_path):
    """使用临时目录 SQLite 文件的 CostTracker。"""
    db = os.path.join(tmp_path, "cost_test.db")
    t = CostTracker(config=SearchRouterConfig(), db_path=db)
    yield t
    t.close()


@pytest.fixture
def mem_tracker():
    t = CostTracker(config=SearchRouterConfig(), db_path=":memory:")
    yield t
    t.close()


# ── 1. 单次任务 ¥2 熔断 ────────────────────────────────

def test_single_task_within_limit(mem_tracker):
    res = mem_tracker.check_single_task(1.5)
    assert res.allowed is True
    assert res.state == CircuitState.OK.value


def test_single_task_exceeds_limit(mem_tracker):
    res = mem_tracker.check_single_task(2.5)
    assert res.allowed is False
    assert res.state == CircuitState.COST_EXCEEDED.value
    assert res.error_code == ErrorCode.COST_EXCEEDED.value


def test_single_task_boundary_2_0_ok(mem_tracker):
    # 恰好 ¥2.0 不算超限（> 才超）
    assert mem_tracker.check_single_task(2.0).allowed is True


# ── 2. 单日 ¥30 熔断 ───────────────────────────────────

def test_daily_within_limit(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 10.0, now=NOW)
    assert mem_tracker.check_daily(now=NOW).should_switch_free is False


def test_daily_exceeds_switch_free(mem_tracker):
    # 累计 > 30 → 切免费源
    for _ in range(4):
        mem_tracker.record_cost("bocha", "t", 8.0, now=NOW)  # 32
    res = mem_tracker.check_daily(now=NOW)
    assert res.should_switch_free is True
    assert res.state == CircuitState.SWITCH_FREE.value
    assert res.allowed is True  # 不拒绝任务，只切源


# ── 3. 单月 ¥300 熔断 ──────────────────────────────────

def test_monthly_exceeds_switch_free_and_notify(mem_tracker):
    # 跨多日累计 > 300（同月不同日，避免单日逻辑干扰）
    for day in range(1, 21):
        mem_tracker.record_cost("bocha", "t", 16.0, now=datetime(2026, 6, day, 9, 0, 0))  # 20*16=320
    res = mem_tracker.check_monthly(now=datetime(2026, 6, 27, 9, 0, 0))
    assert res.should_switch_free is True
    assert res.should_notify is True
    assert res.notification_required is True
    assert res.state == CircuitState.SWITCH_FREE_NOTIFY.value


def test_monthly_within_limit_no_notify(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 100.0, now=NOW)
    assert mem_tracker.check_monthly(now=NOW).should_notify is False


# ── 4. Provider 日 ¥10 熔断 + 暂停 1 小时 ───────────────

def test_provider_daily_exceeds_pauses_1h(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 11.0, now=NOW)
    res = mem_tracker.check_provider_daily("bocha", now=NOW)
    assert res.allowed is False
    assert res.state == CircuitState.PROVIDER_PAUSED.value
    assert mem_tracker.is_provider_paused("bocha", now=NOW) is True
    # 恢复点应为 1 小时后
    assert mem_tracker.provider_resume_at("bocha") == NOW + timedelta(hours=1)
    assert mem_tracker.provider_pause_reason("bocha") == PauseReason.PROVIDER_DAILY_LIMIT.value


def test_provider_daily_pause_recovers_after_1h(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 11.0, now=NOW)
    mem_tracker.check_provider_daily("bocha", now=NOW)
    # 59 分钟仍暂停
    assert mem_tracker.is_provider_paused("bocha", now=NOW + timedelta(minutes=59)) is True
    # 满 1 小时自动恢复
    assert mem_tracker.is_provider_paused("bocha", now=NOW + timedelta(hours=1)) is False


def test_provider_daily_other_provider_not_paused(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 11.0, now=NOW)
    mem_tracker.check_provider_daily("bocha", now=NOW)
    assert mem_tracker.is_provider_paused("tavily", now=NOW) is False


# ── 5. 连续失败 3 次熔断 + 暂停 30 分钟 ─────────────────

def test_consecutive_failures_pause_30min(mem_tracker):
    r1 = mem_tracker.record_failure("glm_search", now=NOW)
    r2 = mem_tracker.record_failure("glm_search", now=NOW)
    assert r1.allowed is True and r2.allowed is True
    assert mem_tracker.consecutive_failures("glm_search") == 2
    r3 = mem_tracker.record_failure("glm_search", now=NOW)
    assert r3.allowed is False
    assert r3.state == CircuitState.PROVIDER_PAUSED.value
    assert mem_tracker.is_provider_paused("glm_search", now=NOW) is True
    assert mem_tracker.provider_resume_at("glm_search") == NOW + timedelta(minutes=30)
    assert mem_tracker.provider_pause_reason("glm_search") == PauseReason.CONSECUTIVE_FAILURES.value


def test_consecutive_failures_recovers_after_30min(mem_tracker):
    for _ in range(3):
        mem_tracker.record_failure("glm_search", now=NOW)
    assert mem_tracker.is_provider_paused("glm_search", now=NOW + timedelta(minutes=29)) is True
    assert mem_tracker.is_provider_paused("glm_search", now=NOW + timedelta(minutes=30)) is False


def test_success_resets_consecutive_failures(mem_tracker):
    mem_tracker.record_failure("glm_search", now=NOW)
    mem_tracker.record_failure("glm_search", now=NOW)
    mem_tracker.record_success("glm_search")
    assert mem_tracker.consecutive_failures("glm_search") == 0
    # 重置后再失败 2 次不应触发暂停
    mem_tracker.record_failure("glm_search", now=NOW)
    r = mem_tracker.record_failure("glm_search", now=NOW)
    assert r.allowed is True
    assert mem_tracker.is_provider_paused("glm_search", now=NOW) is False


# ── 6. CostRecord 写入临时 SQLite ──────────────────────

def test_cost_record_persisted_to_sqlite(tracker, tmp_path):
    rec = tracker.record_cost("bocha", "chinese_industry_news", 0.036, success=True, now=NOW)
    assert rec.id is not None
    assert rec.provider == "bocha"
    # DB 文件确实建在临时目录
    assert os.path.exists(os.path.join(tmp_path, "cost_test.db"))
    # 读回求和
    assert tracker.daily_total(now=NOW) == pytest.approx(0.036)


def test_db_path_is_temp_not_production(tracker, tmp_path):
    assert str(tmp_path) in tracker.db_path
    assert "/prod" not in tracker.db_path and "production" not in tracker.db_path


# ── 7. DailyCostSummary 汇总 ───────────────────────────

def test_daily_summary_aggregation(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 0.036, success=True, now=NOW)
    mem_tracker.record_cost("bocha", "t", 0.060, success=True, now=NOW)
    mem_tracker.record_cost("tavily", "t", 0.112, success=False, now=NOW)
    s = mem_tracker.get_daily_summary(now=NOW)
    assert s.record_count == 3
    assert s.success_count == 2
    assert s.failure_count == 1
    assert s.total_cost == pytest.approx(0.208)
    assert s.per_provider_cost["bocha"] == pytest.approx(0.096)
    assert s.per_provider_cost["tavily"] == pytest.approx(0.112)


def test_daily_summary_excludes_other_days(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 1.0, now=NOW)
    mem_tracker.record_cost("bocha", "t", 5.0, now=NOW - timedelta(days=1))
    s = mem_tracker.get_daily_summary(now=NOW)
    assert s.record_count == 1
    assert s.total_cost == pytest.approx(1.0)


# ── 8. pre_check 综合 ──────────────────────────────────

def test_pre_check_passes_when_clear(mem_tracker):
    assert mem_tracker.pre_check("bocha", 0.036, now=NOW).allowed is True


def test_pre_check_blocks_single_task(mem_tracker):
    res = mem_tracker.pre_check("bocha", 3.0, now=NOW)
    assert res.allowed is False
    assert res.error_code == ErrorCode.COST_EXCEEDED.value


def test_pre_check_blocks_paused_provider(mem_tracker):
    mem_tracker.record_cost("bocha", "t", 11.0, now=NOW)
    mem_tracker.check_provider_daily("bocha", now=NOW)  # 暂停 bocha
    res = mem_tracker.pre_check("bocha", 0.036, now=NOW)
    assert res.allowed is False
    assert res.state == CircuitState.PROVIDER_PAUSED.value


# ── 9. projected = 历史累计 + 本次 estimated_cost（小修）──
#
# 说明：单日 / 单月用例把历史成本分散到多个 provider，使每个 provider
# 日累计 < ¥10，确保不被「Provider 日上限」抢先触发，测试目标明确。

def _spread_daily(tracker, total, now, per=9.0, prefix="p"):
    """把 total 拆成若干 < per 的 record 分散到不同 provider（同一天）。"""
    i = 0
    remaining = round(total, 2)
    while remaining > 1e-9:
        chunk = round(min(per, remaining), 2)
        tracker.record_cost(f"{prefix}{i}", "t", chunk, now=now)
        remaining = round(remaining - chunk, 2)
        i += 1


def test_projected_provider_daily_triggers_pause(mem_tracker):
    # 1) Provider 日累计 9.99 + 本次 0.02 = 10.01 > 10 → 暂停 1 小时
    mem_tracker.record_cost("bocha", "t", 9.99, now=NOW)
    res = mem_tracker.check_provider_daily("bocha", now=NOW, estimated_cost=0.02)
    assert res.allowed is False
    assert res.state == CircuitState.PROVIDER_PAUSED.value
    assert mem_tracker.is_provider_paused("bocha", now=NOW) is True


def test_projected_daily_triggers_switch_free(mem_tracker):
    # 2) 单日累计 29.97 + 本次 0.05 = 30.02 > 30 → switch_free
    _spread_daily(mem_tracker, 29.97, NOW)  # 分散，避免 provider 日抢先
    res = mem_tracker.check_daily(now=NOW, estimated_cost=0.05)
    assert res.should_switch_free is True
    assert res.state == CircuitState.SWITCH_FREE.value


def test_projected_monthly_triggers_switch_free_notify(mem_tracker):
    # 3) 单月累计 299.70 + 本次 0.50 = 300.20 > 300 → switch_free_notify
    for day in range(1, 31):  # 30 天 × 9.99 = 299.70（跨天，避免单日/provider 干扰）
        mem_tracker.record_cost("bocha", "t", 9.99, now=datetime(2026, 6, day, 9, 0, 0))
    res = mem_tracker.check_monthly(now=datetime(2026, 6, 30, 9, 0, 0), estimated_cost=0.50)
    assert res.should_switch_free is True
    assert res.should_notify is True
    assert res.notification_required is True
    assert res.state == CircuitState.SWITCH_FREE_NOTIFY.value


def test_projected_daily_within_limit_no_trigger(mem_tracker):
    # 4) 单日累计 29.00 + 本次 0.50 = 29.50 ≤ 30 → 不触发
    _spread_daily(mem_tracker, 29.00, NOW)
    res = mem_tracker.check_daily(now=NOW, estimated_cost=0.50)
    assert res.should_switch_free is False
    assert res.state == CircuitState.OK.value


def test_projected_monthly_within_limit_no_trigger(mem_tracker):
    # 5) 单月累计 299.00 + 本次 0.50 = 299.50 ≤ 300 → 不触发
    for day in range(1, 31):  # 约 299.00 跨天累计
        mem_tracker.record_cost("bocha", "t", 9.9667, now=datetime(2026, 6, day, 9, 0, 0))
    res = mem_tracker.check_monthly(now=datetime(2026, 6, 30, 9, 0, 0), estimated_cost=0.50)
    assert res.should_switch_free is False
    assert res.should_notify is False


def test_projected_provider_daily_within_limit_no_trigger(mem_tracker):
    # 6) Provider 日累计 9.00 + 本次 0.50 = 9.50 ≤ 10 → 不触发
    mem_tracker.record_cost("bocha", "t", 9.00, now=NOW)
    res = mem_tracker.check_provider_daily("bocha", now=NOW, estimated_cost=0.50)
    assert res.allowed is True
    assert res.state == CircuitState.OK.value
    assert mem_tracker.is_provider_paused("bocha", now=NOW) is False


def test_pre_check_uses_projected_provider_daily(mem_tracker):
    # pre_check 必须使用 projected：9.99 历史 + 0.02 本次 → 拦截
    mem_tracker.record_cost("bocha", "t", 9.99, now=NOW)
    res = mem_tracker.pre_check("bocha", 0.02, now=NOW)
    assert res.allowed is False
    assert res.state == CircuitState.PROVIDER_PAUSED.value


def test_pre_check_uses_projected_daily(mem_tracker):
    # pre_check 单日 projected：29.97 分散历史 + 0.05 本次 → switch_free
    _spread_daily(mem_tracker, 29.97, NOW)
    res = mem_tracker.pre_check("freshprov", 0.05, now=NOW)
    assert res.should_switch_free is True


def test_backward_compat_check_without_estimated_cost(mem_tracker):
    # 单独调用（不传 estimated_cost）退化为纯历史累计判断，兼容旧行为
    _spread_daily(mem_tracker, 29.50, NOW)
    assert mem_tracker.check_daily(now=NOW).should_switch_free is False  # 29.50 ≤ 30
    mem_tracker.record_cost("extra", "t", 1.0, now=NOW)                  # → 30.50
    assert mem_tracker.check_daily(now=NOW).should_switch_free is True
