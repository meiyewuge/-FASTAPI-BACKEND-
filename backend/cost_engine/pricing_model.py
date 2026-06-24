"""Cost pricing model: Seedance 2.0 real per-second billing.

720P pure text-to-video: 46 CNY/M tokens ~ 1 CNY/sec
720P with video input:   28 CNY/M tokens ~ 0.57 CNY/sec
1080P pure text-to-video: 51 CNY/M tokens ~ 1.05 CNY/sec
1080P with video input:  31 CNY/M tokens ~ 0.68 CNY/sec
480P: proportional discount

Change pricing rules only here, not in provider/engine/orchestrator.
"""

from __future__ import annotations

from config import settings

_PRICE_PER_SEC = {
    "480p": {"generate": 0.40, "remix": 0.25},
    "720p": {"generate": 1.00, "remix": 0.57},
    "1080p": {"generate": 1.05, "remix": 0.68},
}


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
