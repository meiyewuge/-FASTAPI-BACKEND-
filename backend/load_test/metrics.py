"""指标采集与统计（延迟分位、计时）。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(s[f], 3)
    return round(s[f] + (s[c] - s[f]) * (k - f), 3)


@dataclass
class LatencyStats:
    samples: list[float] = field(default_factory=list)

    def add(self, ms: float) -> None:
        self.samples.append(ms)

    def summary(self) -> dict:
        n = len(self.samples)
        return {
            "count": n,
            "avg_ms": round(sum(self.samples) / n, 3) if n else 0.0,
            "p50_ms": percentile(self.samples, 50),
            "p95_ms": percentile(self.samples, 95),
            "p99_ms": percentile(self.samples, 99),
            "max_ms": round(max(self.samples), 3) if n else 0.0,
        }


class Timer:
    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.ms = (time.perf_counter() - self._t0) * 1000.0
