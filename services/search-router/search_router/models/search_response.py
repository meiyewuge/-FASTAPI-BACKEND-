"""SearchResponse + SearchResult — P0.2 Phase1扩展版。

新增:
  source_credibility_score: 信源可信度 (NaN=未识别)
  computation_trace: 评分计算追踪
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import math


class ProviderType(str, Enum):
    MOCK = "mock"
    PRIMARY = "primary"
    FALLBACK = "fallback"
    EMERGENCY = "emergency"


class ErrorCode(str, Enum):
    NONE = "none"
    AUTH_FAIL = "auth_fail"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_REQUEST = "invalid_request"
    COST_EXCEEDED = "cost_exceeded"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


NAN_MARKER = float("nan")


def _is_nan(value: float) -> bool:
    return isinstance(value, float) and math.isnan(value)


@dataclass
class SearchResult:
    """P0.2 Phase1扩展 — 新增source_credibility_score + computation_trace。"""
    title: str
    url: str
    summary: str = ""
    source: str = ""
    publish_time: str | None = None
    provider: str = ""
    evidence_excerpt: str = ""
    confidence_score: float = float("nan")
    freshness_score: float = float("nan")
    relevance_score: float = float("nan")
    raw: dict[str, Any] = field(default_factory=dict)
    source_credibility_score: float = float("nan")
    final_score: float = float("nan")
    computation_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        def _sf(v):
            if _is_nan(v):
                return "NaN"
            return round(v, 3)
        return {
            "title": self.title, "url": self.url,
            "summary": self.summary, "source": self.source,
            "publish_time": self.publish_time, "provider": self.provider,
            "evidence_excerpt": self.evidence_excerpt,
            "confidence_score": _sf(self.confidence_score),
            "freshness_score": _sf(self.freshness_score),
            "relevance_score": _sf(self.relevance_score),
            "source_credibility_score": _sf(self.source_credibility_score),
            "final_score": _sf(self.final_score),
            "computation_trace": self.computation_trace,
        }


@dataclass
class SearchResponse:
    success: bool = True
    provider: str = "mock"
    provider_type: ProviderType = ProviderType.MOCK
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    latency_ms: int = 0
    credits_used: int = 0
    estimated_cost: float = 0.0
    error: str | None = None
    error_code: str = "none"

    def __post_init__(self):
        if self.total_results == 0 and self.results:
            self.total_results = len(self.results)

    def to_dict(self) -> dict:
        return {
            "success": self.success, "provider": self.provider,
            "provider_type": self.provider_type.value if hasattr(self.provider_type, "value") else str(self.provider_type),
            "results": [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in self.results],
            "total_results": self.total_results, "latency_ms": self.latency_ms,
            "credits_used": self.credits_used,
            "estimated_cost": round(self.estimated_cost, 4),
            "error": self.error, "error_code": self.error_code,
        }
