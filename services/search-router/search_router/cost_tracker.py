"""CostTracker — 成本追踪与五级熔断（T2B）。

五级熔断阈值（来自 SearchRouterConfig，吴哥已确认）：
    单次任务上限     ¥2.0    → COST_EXCEEDED（拒绝本次）
    单日上限         ¥30.0   → 切免费源（should_switch_free）
    单月上限         ¥300.0  → 切免费源 + 通知吴哥（should_notify）
    单 Provider 日上限 ¥10.0 → 暂停该 Provider 1 小时
    连续失败         3 次    → 暂停该 Provider 30 分钟

⚠️ T2B 安全约束：
    - SQLite 持久化，但默认内存库（":memory:"）；测试用临时目录 / 临时库。
      绝不写生产路径。
    - 不联网、不真实调用 Provider、不接飞书真实通知（仅返回 should_notify 标志）。
    - 所有时间判断支持注入 now（datetime），测试无需 sleep 真实时间。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from search_router.config import SearchRouterConfig
from search_router.models.search_response import ErrorCode
from search_router.models.cost_record import (
    CostRecord,
    DailyCostSummary,
    CostCheckResult,
    CircuitState,
    PauseReason,
)


class CostTracker:
    """成本追踪 + 五级熔断 + 自动恢复判断。"""

    # 暂停时长（秒）
    PROVIDER_DAILY_PAUSE_SECONDS = 3600   # Provider 日上限 → 暂停 1 小时
    CONSECUTIVE_FAIL_PAUSE_SECONDS = 1800  # 连续失败 → 暂停 30 分钟

    def __init__(
        self,
        config: SearchRouterConfig | None = None,
        db_path: str = ":memory:",
    ) -> None:
        """初始化。

        Args:
            config: 配置（提供熔断阈值）。None 时用默认 SearchRouterConfig()。
            db_path: SQLite 路径。默认内存库；测试传临时文件路径。
                     **不得传生产路径。**
        """
        self.config = config or SearchRouterConfig()
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

        # 内存态：Provider 暂停信息与连续失败计数
        # provider -> {"until": datetime, "reason": PauseReason}
        self._paused: dict[str, dict] = {}
        # provider -> 连续失败次数
        self._consecutive_failures: dict[str, int] = {}

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cost_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                task_type TEXT NOT NULL,
                cost REAL NOT NULL,
                success INTEGER NOT NULL,
                error_code TEXT NOT NULL,
                credits_used INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── 记录 ──────────────────────────────────────────

    def record_cost(
        self,
        provider: str,
        task_type: str,
        cost: float,
        success: bool = True,
        error_code: str = "none",
        credits_used: int = 0,
        now: datetime | None = None,
    ) -> CostRecord:
        """写入一条成本记录到（临时）SQLite，并回填自增主键。"""
        ts = (now or datetime.now()).isoformat()
        cur = self._conn.execute(
            "INSERT INTO cost_records "
            "(timestamp, provider, task_type, cost, success, error_code, credits_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, provider, task_type, float(cost), 1 if success else 0, error_code, int(credits_used)),
        )
        self._conn.commit()
        return CostRecord(
            id=cur.lastrowid,
            timestamp=ts,
            provider=provider,
            task_type=task_type,
            cost=float(cost),
            success=success,
            error_code=error_code,
            credits_used=credits_used,
        )

    # ── 求和辅助 ──────────────────────────────────────

    def _sum_where(self, like_prefix: str, provider: str | None = None) -> float:
        sql = "SELECT COALESCE(SUM(cost), 0.0) AS s FROM cost_records WHERE timestamp LIKE ?"
        params: list = [like_prefix + "%"]
        if provider is not None:
            sql += " AND provider = ?"
            params.append(provider)
        row = self._conn.execute(sql, params).fetchone()
        return float(row["s"] or 0.0)

    def daily_total(self, now: datetime | None = None) -> float:
        now = now or datetime.now()
        return self._sum_where(now.strftime("%Y-%m-%d"))

    def monthly_total(self, now: datetime | None = None) -> float:
        now = now or datetime.now()
        return self._sum_where(now.strftime("%Y-%m"))

    def provider_daily_total(self, provider: str, now: datetime | None = None) -> float:
        now = now or datetime.now()
        return self._sum_where(now.strftime("%Y-%m-%d"), provider=provider)

    # ── 五级检查 ──────────────────────────────────────

    def check_single_task(self, cost: float) -> CostCheckResult:
        """单次任务成本 > ¥2.0 → 拒绝，COST_EXCEEDED。"""
        if cost > self.config.cost_limit_single_task:
            return CostCheckResult(
                allowed=False,
                state=CircuitState.COST_EXCEEDED.value,
                error_code=ErrorCode.COST_EXCEEDED.value,
                reason=f"单次任务成本 ¥{cost} 超过上限 ¥{self.config.cost_limit_single_task}",
            )
        return CostCheckResult(allowed=True, state=CircuitState.OK.value)

    def check_daily(self, now: datetime | None = None, estimated_cost: float = 0.0) -> CostCheckResult:
        """单日「历史累计 + 本次 estimated_cost」> ¥30.0 → 切免费源。

        estimated_cost 默认 0.0：单独调用退化为纯历史累计判断（向后兼容）。
        """
        projected = self.daily_total(now) + estimated_cost
        if projected > self.config.cost_limit_daily:
            return CostCheckResult(
                allowed=True,  # 不拒绝任务，但应切免费源
                state=CircuitState.SWITCH_FREE.value,
                should_switch_free=True,
                reason=f"单日预计成本 ¥{round(projected, 4)} 超过上限 "
                       f"¥{self.config.cost_limit_daily}，切免费源",
            )
        return CostCheckResult(allowed=True, state=CircuitState.OK.value)

    def check_monthly(self, now: datetime | None = None, estimated_cost: float = 0.0) -> CostCheckResult:
        """单月「历史累计 + 本次 estimated_cost」> ¥300.0 → 切免费源 + 通知标志。

        estimated_cost 默认 0.0：单独调用退化为纯历史累计判断（向后兼容）。
        （仅返回 should_notify 标志，不发真实通知。）
        """
        projected = self.monthly_total(now) + estimated_cost
        if projected > self.config.cost_limit_monthly:
            return CostCheckResult(
                allowed=True,
                state=CircuitState.SWITCH_FREE_NOTIFY.value,
                should_switch_free=True,
                should_notify=True,
                notification_required=True,
                reason=f"单月预计成本 ¥{round(projected, 4)} 超过上限 "
                       f"¥{self.config.cost_limit_monthly}，切免费源并应通知吴哥",
            )
        return CostCheckResult(allowed=True, state=CircuitState.OK.value)

    def check_provider_daily(
        self,
        provider: str,
        now: datetime | None = None,
        estimated_cost: float = 0.0,
    ) -> CostCheckResult:
        """单 Provider 日「历史累计 + 本次 estimated_cost」> ¥10.0 → 暂停 1 小时。

        estimated_cost 默认 0.0：单独调用退化为纯历史累计判断（向后兼容）。
        """
        now = now or datetime.now()
        projected = self.provider_daily_total(provider, now) + estimated_cost
        if projected > self.config.cost_limit_provider_daily:
            self._pause_provider(
                provider,
                PauseReason.PROVIDER_DAILY_LIMIT,
                self.PROVIDER_DAILY_PAUSE_SECONDS,
                now,
            )
            return CostCheckResult(
                allowed=False,
                state=CircuitState.PROVIDER_PAUSED.value,
                reason=f"Provider {provider} 日预计成本 ¥{round(projected, 4)} 超过上限 "
                       f"¥{self.config.cost_limit_provider_daily}，暂停 1 小时",
            )
        return CostCheckResult(allowed=True, state=CircuitState.OK.value)

    # ── 连续失败熔断 ──────────────────────────────────

    def record_success(self, provider: str) -> None:
        """成功 → 重置该 Provider 连续失败计数。"""
        self._consecutive_failures[provider] = 0

    def record_failure(self, provider: str, now: datetime | None = None) -> CostCheckResult:
        """失败 +1；达到上限（默认 3）→ 暂停该 Provider 30 分钟。"""
        now = now or datetime.now()
        n = self._consecutive_failures.get(provider, 0) + 1
        self._consecutive_failures[provider] = n
        if n >= self.config.provider_max_consecutive_failures:
            self._pause_provider(
                provider,
                PauseReason.CONSECUTIVE_FAILURES,
                self.CONSECUTIVE_FAIL_PAUSE_SECONDS,
                now,
            )
            return CostCheckResult(
                allowed=False,
                state=CircuitState.PROVIDER_PAUSED.value,
                reason=f"Provider {provider} 连续失败 {n} 次，暂停 30 分钟",
            )
        return CostCheckResult(allowed=True, state=CircuitState.OK.value)

    def consecutive_failures(self, provider: str) -> int:
        return self._consecutive_failures.get(provider, 0)

    # ── 暂停 / 恢复 ────────────────────────────────────

    def _pause_provider(
        self,
        provider: str,
        reason: PauseReason,
        seconds: int,
        now: datetime,
    ) -> None:
        self._paused[provider] = {
            "until": now + timedelta(seconds=seconds),
            "reason": reason,
        }

    def is_provider_paused(self, provider: str, now: datetime | None = None) -> bool:
        """该 Provider 当前是否处于暂停中（支持自动恢复判断）。"""
        info = self._paused.get(provider)
        if not info:
            return False
        now = now or datetime.now()
        if now >= info["until"]:
            # 自动恢复：到点清除暂停态与失败计数
            del self._paused[provider]
            self._consecutive_failures[provider] = 0
            return False
        return True

    def provider_resume_at(self, provider: str) -> datetime | None:
        info = self._paused.get(provider)
        return info["until"] if info else None

    def provider_pause_reason(self, provider: str) -> str:
        info = self._paused.get(provider)
        return info["reason"].value if info else PauseReason.NONE.value

    # ── 汇总 ──────────────────────────────────────────

    def get_daily_summary(self, now: datetime | None = None) -> DailyCostSummary:
        """汇总指定日（默认今天）的成本。"""
        now = now or datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT provider, cost, success FROM cost_records WHERE timestamp LIKE ?",
            (date_str + "%",),
        ).fetchall()

        summary = DailyCostSummary(date=date_str)
        for r in rows:
            summary.record_count += 1
            summary.total_cost += float(r["cost"])
            if r["success"]:
                summary.success_count += 1
            else:
                summary.failure_count += 1
            p = r["provider"]
            summary.per_provider_cost[p] = summary.per_provider_cost.get(p, 0.0) + float(r["cost"])
        return summary

    # ── 任务前置综合检查 ──────────────────────────────

    def pre_check(
        self,
        provider: str,
        estimated_cost: float,
        now: datetime | None = None,
    ) -> CostCheckResult:
        """任务前置综合检查（顺序：暂停 → 单次 → Provider 日 → 单日 → 单月）。

        返回首个命中的熔断结果；全部通过则 allowed=True。
        纯本地计算，不联网、不调用 Provider。
        """
        now = now or datetime.now()

        if self.is_provider_paused(provider, now):
            return CostCheckResult(
                allowed=False,
                state=CircuitState.PROVIDER_PAUSED.value,
                reason=f"Provider {provider} 处于暂停中（{self.provider_pause_reason(provider)}）",
            )

        single = self.check_single_task(estimated_cost)
        if not single.allowed:
            return single

        # 累计熔断一律用 projected = 历史累计 + 本次 estimated_cost 判断
        prov = self.check_provider_daily(provider, now, estimated_cost=estimated_cost)
        if not prov.allowed:
            return prov

        monthly = self.check_monthly(now, estimated_cost=estimated_cost)
        if monthly.should_switch_free:
            return monthly

        daily = self.check_daily(now, estimated_cost=estimated_cost)
        if daily.should_switch_free:
            return daily

        return CostCheckResult(allowed=True, state=CircuitState.OK.value)
