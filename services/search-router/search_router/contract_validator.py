"""Contract Validator — P0.2 Phase1核心模块。

NaN在CandidatePool.route_card之前被拦截。
NaN→contract_error_quarantine, 合法0.0→按0.30正常discard。
NaN进入CandidatePool比例必须为0%。
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any
from search_router.models.search_response import SearchResult, _is_nan


@dataclass
class ValidationResult:
    is_valid: bool = True
    quarantine_reason: str = ""
    nan_fields: list = field(default_factory=list)
    valid_zero_fields: list = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    def to_dict(self):
        return {"is_valid": self.is_valid, "quarantine_reason": self.quarantine_reason,
                "nan_fields": self.nan_fields, "valid_zero_fields": self.valid_zero_fields}


class ContractValidator:
    """NaN拦截器 — 未识别信源/无日期→NaN→quarantine, 合法0.0→放行。"""

    REQUIRED_SCORE_FIELDS = ["source_credibility_score", "freshness_score", "relevance_score", "confidence_score"]

    def validate(self, result):
        nan_fields = []
        valid_zero_fields = []
        for fn in self.REQUIRED_SCORE_FIELDS:
            val = getattr(result, fn, None)
            if val is None:
                nan_fields.append(fn)
            elif isinstance(val, float) and math.isnan(val):
                nan_fields.append(fn)
            elif isinstance(val, float) and val == 0.0:
                valid_zero_fields.append(fn)
        trace = {"module": "contract_validator", "nan_fields": nan_fields,
                 "valid_zero_fields": valid_zero_fields}
        if nan_fields:
            reasons = []
            for f in nan_fields:
                if f == "source_credibility_score": reasons.append("信源未识别(NaN)")
                elif f == "freshness_score": reasons.append("无发布日期(NaN)")
                elif f == "relevance_score": reasons.append("相关性无法计算(NaN)")
                elif f == "confidence_score": reasons.append("置信度无法计算(NaN)")
            return ValidationResult(is_valid=False, quarantine_reason="; ".join(reasons),
                                    nan_fields=nan_fields, valid_zero_fields=valid_zero_fields, trace=trace)
        return ValidationResult(is_valid=True, nan_fields=[], valid_zero_fields=valid_zero_fields, trace=trace)

    def validate_batch(self, results):
        valid, quarantined = [], []
        for r in results:
            vr = self.validate(r)
            if vr.is_valid: valid.append(r)
            else: quarantined.append((r, vr))
        return {"valid": valid, "quarantined": quarantined,
                "stats": {"total": len(results), "valid": len(valid),
                          "quarantined": len(quarantined)}}
