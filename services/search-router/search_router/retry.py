"""RetryPolicy — 重试与指数退避策略（T2B）。

参数：
    max_retries = 2
    base_delay_seconds = 5
    max_delay_seconds = 30
    backoff_factor = 2.0

可重试错误（retryable）：
    TIMEOUT / RATE_LIMIT / NETWORK_ERROR / SERVER_ERROR
不可重试错误（non_retryable）：
    AUTH_FAIL / QUOTA_EXCEEDED / INVALID_REQUEST / COST_EXCEEDED

⚠️ T2B 阶段：
    - 退避 sleep 可注入（默认 asyncio.sleep）；测试注入假 sleep，不真实等待。
    - 不联网、不真实调用 Provider。execute() 只是围绕一个返回 SearchResponse
      的协程工厂做重试控制。
"""

from __future__ import annotations

from typing import Awaitable, Callable

from search_router.models.search_response import SearchResponse, ErrorCode


# 可重试 / 不可重试错误码集合
RETRYABLE_ERROR_CODES: frozenset[str] = frozenset({
    ErrorCode.TIMEOUT.value,
    ErrorCode.RATE_LIMIT.value,
    ErrorCode.NETWORK_ERROR.value,
    ErrorCode.SERVER_ERROR.value,
})

NON_RETRYABLE_ERROR_CODES: frozenset[str] = frozenset({
    ErrorCode.AUTH_FAIL.value,
    ErrorCode.QUOTA_EXCEEDED.value,
    ErrorCode.INVALID_REQUEST.value,
    ErrorCode.COST_EXCEEDED.value,
})


class RetryPolicy:
    """重试策略：指数退避 + 错误分类。"""

    def __init__(
        self,
        max_retries: int = 2,
        base_delay_seconds: float = 5.0,
        max_delay_seconds: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.backoff_factor = backoff_factor

    # ── 分类 ──────────────────────────────────────────

    def is_retryable(self, error_code: str) -> bool:
        """错误码是否可重试。"""
        return error_code in RETRYABLE_ERROR_CODES

    def should_retry(self, error_code: str, attempt: int) -> bool:
        """在第 attempt 次（从 0 计）失败后是否还应重试。

        条件：错误可重试 且 已用重试次数未达上限。
        attempt 表示「已经失败的次数」，retry 上限为 max_retries。
        """
        if not self.is_retryable(error_code):
            return False
        return attempt < self.max_retries

    # ── 退避计算 ──────────────────────────────────────

    def compute_delay(self, attempt: int) -> float:
        """第 attempt 次重试前的退避秒数（从 0 计）。

        delay = min(base_delay * backoff_factor ** attempt, max_delay)
        例（base=5, factor=2, max=30）：
            attempt 0 → 5
            attempt 1 → 10
            attempt 2 → 20
            attempt 3 → 30（被 max_delay 截断，原始 40）
        """
        raw = self.base_delay_seconds * (self.backoff_factor ** attempt)
        return min(raw, self.max_delay_seconds)

    # ── 执行（围绕协程工厂做重试，sleep 可注入）──────────

    async def execute(
        self,
        coro_factory: Callable[[], Awaitable[SearchResponse]],
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> SearchResponse:
        """执行 coro_factory，按策略对可重试错误重试。

        Args:
            coro_factory: 无参可调用，每次调用返回一个 awaitable[SearchResponse]。
            sleep: 退避等待函数（async）。默认 asyncio.sleep；测试可注入假 sleep。

        Returns:
            最后一次（或成功的）SearchResponse。
        """
        if sleep is None:
            import asyncio
            sleep = asyncio.sleep

        attempt = 0
        response = await coro_factory()
        while True:
            if response.success:
                return response
            if not self.should_retry(response.error_code, attempt):
                return response
            await sleep(self.compute_delay(attempt))
            attempt += 1
            response = await coro_factory()
