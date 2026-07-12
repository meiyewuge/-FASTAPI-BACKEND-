"""Freshness Scorer — P0.2 Phase1。

无发布日期→NaN→quarantine，Phase1不自创默认半衰期。
"""
from __future__ import annotations
import math
from datetime import datetime
from typing import Any

NAN_SCORE = float("nan")
HALF_LIFE_DAYS = {"trend": 90, "policy": 180, "technology": 60, "default": 90}


def score_freshness(publish_time, knowledge_type="default", reference_time=None):
    trace = {"module": "freshness_scorer", "input_publish_time": str(publish_time),
             "knowledge_type": knowledge_type}
    if not publish_time or not str(publish_time).strip():
        trace["reason"] = "publish_time为空，标记NaN"
        trace["decision"] = "NaN → contract_error_quarantine"
        return NAN_SCORE, trace
    try:
        pub_str = str(publish_time).strip()
        pub_dt = None
        for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S+08:00", "%Y-%m-%d"]:
            try:
                pub_dt = datetime.strptime(
                    pub_str.replace("+08:00", "+0800").replace("+00:00", "+0000"), fmt)
                if pub_dt.tzinfo:
                    pub_dt = pub_dt.replace(tzinfo=None)
                break
            except ValueError:
                continue
        if pub_dt is None:
            trace["reason"] = f"无法解析publish_time {publish_time}，标记NaN"
            trace["decision"] = "NaN → contract_error_quarantine"
            return NAN_SCORE, trace
    except Exception as e:
        trace["reason"] = f"解析异常: {e}，标记NaN"
        return NAN_SCORE, trace
    ref = reference_time or datetime.now()
    age_days = max(0, (ref - pub_dt).days)
    half_life = HALF_LIFE_DAYS.get(knowledge_type, HALF_LIFE_DAYS["default"])
    score = math.exp(-math.log(2) * age_days / half_life)
    score = max(0.0, min(1.0, score))
    trace["age_days"] = age_days
    trace["half_life_days"] = half_life
    trace["reason"] = f"发布于{age_days}天前(半衰期{half_life}天), freshness={score:.3f}"
    return score, trace
