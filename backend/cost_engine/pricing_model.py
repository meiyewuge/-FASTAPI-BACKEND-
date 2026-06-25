"""Cost pricing model: Seedance 2.0 real per-second billing（价格单一真源，勿散落硬编码）。

火山官方定价（BUG-2 修正，2026-06）：
  720P  纯文生(generate)      : ¥1.00/sec ✅
  1080P 纯文生(generate)      : ¥2.48/sec  ← 旧代码误填 ¥1.05，已修正
  720P  含视频输入(remix)      : ¥0.57/sec
  1080P 含视频输入(remix)      : ¥0.68/sec
  480P : 按比例折扣

所有价格只在本文件维护；provider/engine/orchestrator/ledger 一律调用 price()/estimate_cost()。
"""

from __future__ import annotations

from config import settings

# 每秒单价（元）。generate=纯文生（A台母视频）；remix=含视频输入（B台裂变/含源）
_PRICE_PER_SEC = {
    "480p": {"generate": 0.40, "remix": 0.25},
    "720p": {"generate": 1.00, "remix": 0.57},
    "1080p": {"generate": 2.48, "remix": 0.68},   # BUG-2：1080p generate 1.05 → 2.48
}


def per_sec(resolution: str, mode: str) -> float:
    """单段每秒单价。mode ∈ {generate, remix}。"""
    res = (resolution or "720p").lower()
    return _PRICE_PER_SEC.get(res, _PRICE_PER_SEC["720p"]).get(mode, 1.0)


def estimate_cost(api_name: str, duration: float, resolution: str = "1080p") -> float:
    """按秒预估金额（用于 cost ledger 预扣费 / preview 费用预估）。"""
    mode = "generate" if "generate" in api_name else "remix"
    d = float(duration or 0)
    return round(per_sec(resolution, mode) * d, 2) if d > 0 else 0.0


def unit_price(api_name: str) -> float:
    return {
        "video.generate.a": settings.cost_per_mother,
        "video.remix.b": settings.cost_per_clip,
    }.get(api_name, 0.0)


def price(api_name: str, units: float, duration: float | None = None, resolution: str = "720p") -> float:
    if duration and duration > 0:
        res = (resolution or "720p").lower()
        mode = "generate" if "generate" in api_name else "remix"
        default_prices = _PRICE_PER_SEC["720p"]
        per_sec = _PRICE_PER_SEC.get(res, default_prices).get(mode, 1.0)
        return round(per_sec * duration, 2)
    return unit_price(api_name) * (units or 1)
