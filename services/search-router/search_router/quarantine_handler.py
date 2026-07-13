"""Quarantine Handler — P0.2 Phase1影子quarantine。

存储被ContractValidator拦截的结果，记录隔离原因和computation_trace。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from search_router.models.search_response import SearchResult
from search_router.contract_validator import ValidationResult


@dataclass
class QuarantinedResult:
    result: SearchResult
    validation: ValidationResult
    quarantine_time: str = ""
    quarantine_category: str = ""

    def to_dict(self):
        return {"quarantine_category": self.quarantine_category,
                "quarantine_reason": self.validation.quarantine_reason,
                "nan_fields": self.validation.nan_fields,
                "result_title": self.result.title[:100],
                "computation_trace": self.result.computation_trace}


class QuarantineHandler:
    def __init__(self):
        self._quarantined = []

    def add(self, result, validation):
        from datetime import datetime
        cat = "contract_error_quarantine"
        if "信源未识别" in validation.quarantine_reason: cat = "unrecognized_source"
        elif "无发布日期" in validation.quarantine_reason: cat = "missing_publish_date"
        elif "置信度无法计算" in validation.quarantine_reason: cat = "confidence_nan"
        qr = QuarantinedResult(result=result, validation=validation,
                                quarantine_time=datetime.now().isoformat(),
                                quarantine_category=cat)
        self._quarantined.append(qr)
        return qr

    @property
    def quarantined(self): return list(self._quarantined)

    def stats(self):
        cats = {}
        for qr in self._quarantined:
            cats[qr.quarantine_category] = cats.get(qr.quarantine_category, 0) + 1
        return {"total_quarantined": len(self._quarantined), "by_category": cats}
