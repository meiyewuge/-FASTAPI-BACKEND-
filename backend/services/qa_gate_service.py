"""QA 门禁服务（V4 P2A · 框架）。

P2A 复用 b_engine/qa_checks.py 已有的 4 道 hard gate（duration/pts/playable/md5），
另预留若干 soft gate 占位（P2B 实现真实检查逻辑）。

P2A 不在 preview 路径执行真实 QA（无产物），仅暴露门禁定义与 hard gate 包装。
"""

from __future__ import annotations

from b_engine import qa_checks
from config import settings

# 4 道 hard gate（P2A 已实现，复用 b_engine/qa_checks）
HARD_GATES = ["duration_check", "pts_check", "playback_validate", "md5_duplicate_check"]

# 框架性 soft gate（P2A 仅结构预留，P2B 实现）
SOFT_GATES = [
    "license_check",
    "license_claim_check",
    "brand_presence_check",
    "subtitle_readability_check",
]


def list_gates() -> dict:
    return {"hard_gates": list(HARD_GATES), "soft_gates": list(SOFT_GATES)}


def run_hard_gates(path: str, batch_md5: set[str] | None = None,
                   lo: float | None = None, hi: float | None = None,
                   tol: float | None = None) -> dict:
    """复用 b_engine/qa_checks.run_gates 跑 4 道 hard gate。

    P2B execute 阶段调用；P2A 仅提供包装，preview 路径不调用。
    """
    lo = settings.b_remix_target_lo if lo is None else lo
    hi = settings.b_remix_target_hi if hi is None else hi
    tol = settings.b_remix_duration_tol if tol is None else tol
    return qa_checks.run_gates(path, batch_md5 or set(), lo, hi, tol)


def soft_gate_stub(gate: str) -> dict:
    """soft gate 占位（P2A 未实现，返回 not_implemented）。"""
    if gate not in SOFT_GATES:
        raise ValueError(f"未知 soft gate: {gate}")
    return {"gate": gate, "result": "not_implemented", "detail": "P2A 仅结构预留，P2B 实现"}
