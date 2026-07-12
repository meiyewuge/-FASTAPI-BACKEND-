"""测试 RetryPolicy 指数退避 + 错误分类（T2B）。

测试不 sleep 真实时间：execute() 注入假 sleep（记录调用，立即返回）。
不联网、不真实调用 Provider。
"""

import asyncio

import pytest

from search_router.retry import (
    RetryPolicy,
    RETRYABLE_ERROR_CODES,
    NON_RETRYABLE_ERROR_CODES,
)
from search_router.models.search_response import SearchResponse, ProviderType, ErrorCode


# ── 错误分类 ───────────────────────────────────────────

def test_retryable_set():
    assert RETRYABLE_ERROR_CODES == frozenset({
        "timeout", "rate_limit", "network_error", "server_error",
    })


def test_non_retryable_set():
    assert NON_RETRYABLE_ERROR_CODES == frozenset({
        "auth_fail", "quota_exceeded", "invalid_request", "cost_exceeded",
    })


@pytest.mark.parametrize("code", ["timeout", "rate_limit", "network_error", "server_error"])
def test_is_retryable_true(code):
    assert RetryPolicy().is_retryable(code) is True


@pytest.mark.parametrize("code", ["auth_fail", "quota_exceeded", "invalid_request", "cost_exceeded", "none"])
def test_is_retryable_false(code):
    assert RetryPolicy().is_retryable(code) is False


# ── 指数退避计算 ───────────────────────────────────────

def test_backoff_sequence():
    r = RetryPolicy()  # base=5, factor=2, max=30
    assert r.compute_delay(0) == 5.0
    assert r.compute_delay(1) == 10.0
    assert r.compute_delay(2) == 20.0


def test_backoff_capped_at_max_delay():
    r = RetryPolicy()
    assert r.compute_delay(3) == 30.0    # 原始 40 → 截断 30
    assert r.compute_delay(10) == 30.0   # 远超也截断


def test_backoff_custom_params():
    r = RetryPolicy(base_delay_seconds=2, backoff_factor=3.0, max_delay_seconds=50)
    assert r.compute_delay(0) == 2.0
    assert r.compute_delay(1) == 6.0
    assert r.compute_delay(2) == 18.0
    assert r.compute_delay(3) == 50.0  # 54 → 截断


# ── should_retry ───────────────────────────────────────

def test_should_retry_retryable_within_limit():
    r = RetryPolicy()  # max_retries=2
    assert r.should_retry("timeout", attempt=0) is True
    assert r.should_retry("timeout", attempt=1) is True


def test_should_retry_stops_at_max():
    r = RetryPolicy()
    assert r.should_retry("timeout", attempt=2) is False


def test_should_retry_non_retryable_never():
    r = RetryPolicy()
    assert r.should_retry("auth_fail", attempt=0) is False


# ── execute（注入假 sleep）─────────────────────────────

def _resp(success, error_code="none"):
    return SearchResponse(
        success=success,
        provider="bocha",
        provider_type=ProviderType.PRIMARY,
        error=None if success else "err",
        error_code=error_code,
    )


class _FakeSleep:
    def __init__(self):
        self.delays = []

    async def __call__(self, seconds):
        self.delays.append(seconds)  # 记录但不真实等待


def test_execute_success_no_retry():
    r = RetryPolicy()
    sleep = _FakeSleep()
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return _resp(True)

    resp = asyncio.run(r.execute(factory, sleep=sleep))
    assert resp.success is True
    assert calls["n"] == 1
    assert sleep.delays == []  # 未退避


def test_execute_retryable_retries_twice_then_gives_up():
    r = RetryPolicy()  # max_retries=2
    sleep = _FakeSleep()
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return _resp(False, "server_error")  # 始终失败且可重试

    resp = asyncio.run(r.execute(factory, sleep=sleep))
    assert resp.success is False
    assert calls["n"] == 3              # 1 次 + 2 次重试
    assert sleep.delays == [5.0, 10.0]  # 两次退避，未真实等待


def test_execute_non_retryable_no_retry():
    r = RetryPolicy()
    sleep = _FakeSleep()
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return _resp(False, "auth_fail")

    resp = asyncio.run(r.execute(factory, sleep=sleep))
    assert resp.success is False
    assert calls["n"] == 1
    assert sleep.delays == []


def test_execute_retryable_then_success():
    r = RetryPolicy()
    sleep = _FakeSleep()
    seq = [_resp(False, "timeout"), _resp(True)]
    calls = {"n": 0}

    async def factory():
        out = seq[calls["n"]]
        calls["n"] += 1
        return out

    resp = asyncio.run(r.execute(factory, sleep=sleep))
    assert resp.success is True
    assert calls["n"] == 2
    assert sleep.delays == [5.0]
