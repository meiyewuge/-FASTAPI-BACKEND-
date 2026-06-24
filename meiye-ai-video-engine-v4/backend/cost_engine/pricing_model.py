"""计价模型：单价策略。改计费规则（按条 → 按秒/按帧）只动这里。"""

from __future__ import annotations

from config import settings


def unit_price(api_name: str) -> float:
    """每单位用量价格。"""
    return {
        "video.generate.a": settings.cost_per_mother,
        "video.remix.b": settings.cost_per_clip,
    }.get(api_name, 0.0)


def price(api_name: str, units: float, duration: float | None = None) -> float:
    """金额 = 单价 × 用量。duration 预留给按秒计费。"""
    return unit_price(api_name) * (units or 1)
