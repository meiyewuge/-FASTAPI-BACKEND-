"""Confidence Scorer — P0.2 Phase1。

加权综合: confidence = 0.45*src_cred + 0.25*freshness + 0.30*relevance
任一输入NaN→confidence NaN→quarantine。
Tavily relevance经tanh规范化，不直接等于confidence。
GLM不硬编码0.75。
"""
from __future__ import annotations
import math
from typing import Any

WEIGHTS = {"source_credibility": 0.45, "freshness": 0.25, "relevance": 0.30}
NAN_SCORE = float("nan")


def score_confidence(source_credibility_score, freshness_score, relevance_score, provider=""):
    trace = {"module": "confidence_scorer", "formula_version": "P0.2_Phase1_V1.2",
             "provider": provider,
             "inputs": {"source_credibility_score": source_credibility_score,
                        "freshness_score": freshness_score,
                        "relevance_score": relevance_score},
             "weights": WEIGHTS}
    nan_fields = []
    for name, val in [("source_credibility_score", source_credibility_score),
                      ("freshness_score", freshness_score),
                      ("relevance_score", relevance_score)]:
        if isinstance(val, float) and math.isnan(val):
            nan_fields.append(name)
    if nan_fields:
        trace["nan_fields"] = nan_fields
        trace["reason"] = f"输入含NaN{nan_fields}，confidence标记NaN"
        trace["decision"] = "NaN → contract_error_quarantine"
        return NAN_SCORE, trace
    ws, wf, wr = WEIGHTS["source_credibility"], WEIGHTS["freshness"], WEIGHTS["relevance"]
    conf = ws * source_credibility_score + wf * freshness_score + wr * relevance_score
    conf = max(0.0, min(1.0, conf))
    trace["calculation"] = (f"{ws}*{source_credibility_score:.3f} + "
                            f"{wf}*{freshness_score:.3f} + "
                            f"{wr}*{relevance_score:.3f} = {conf:.3f}")
    trace["reason"] = f"加权计算: confidence={conf:.3f}"
    return conf, trace


def compute_relevance_from_tavily_score(tavily_score):
    trace = {"module": "confidence_scorer",
             "function": "compute_relevance_from_tavily_score",
             "input_tavily_score": tavily_score}
    if tavily_score <= 0:
        rel = 0.0
    else:
        rel = math.tanh(tavily_score * 1.5)
    trace["formula"] = "tanh(score * 1.5)"
    trace["reason"] = f"Tavily score {tavily_score:.3f} → relevance {rel:.3f}"
    return rel, trace


def compute_relevance_from_bocha(snippet_length, has_url):
    trace = {"module": "confidence_scorer",
             "function": "compute_relevance_from_bocha",
             "snippet_length": snippet_length, "has_url": has_url}
    base = 0.3
    if snippet_length >= 500:
        base += 0.25
    elif snippet_length >= 100:
        base += 0.15
    elif snippet_length > 0:
        base += 0.05
    if has_url:
        base += 0.10
    rel = min(base, 0.95)
    trace["reason"] = f"snippet_len={snippet_length}, has_url={has_url} → rel={rel:.3f}"
    return rel, trace
