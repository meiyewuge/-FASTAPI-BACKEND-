"""裂变变体服务（V4 P2A · 框架）。

variant CRUD + QA 状态管理。P2A preview 不入库（fission_plan_service 直接返回 JSON），
本模块提供 P2B execute 阶段落库/查询/状态流转所需的 tenant 隔离接口骨架。

P2A 不写 videos、不调 remixer、不触发火山；output_video_id 在 P2B 才写。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models import FissionVariant

_VALID_QA = {"pending", "pass", "warn", "fail"}
_VALID_FINAL = {"pass", "failed", "skipped"}


def list_by_plan(db: Session, tenant_id: str, fission_plan_id: str) -> list[dict]:
    rows = (
        db.query(FissionVariant)
        .filter(FissionVariant.fission_plan_id == fission_plan_id,
                FissionVariant.tenant_id == tenant_id)
        .order_by(FissionVariant.sort_order.asc())
        .all()
    )
    return [_to_dict(r) for r in rows]


def get(db: Session, tenant_id: str, variant_id: str) -> dict | None:
    row = (
        db.query(FissionVariant)
        .filter(FissionVariant.variant_id == variant_id,
                FissionVariant.tenant_id == tenant_id)
        .first()
    )
    return _to_dict(row) if row else None


def update_qa_status(db: Session, tenant_id: str, variant_id: str,
                     qa_status: str, final_status: str | None = None) -> dict | None:
    """更新 QA 状态（tenant 隔离）。P2B QA 回写用。"""
    if qa_status not in _VALID_QA:
        raise ValueError(f"非法 qa_status: {qa_status}")
    if final_status is not None and final_status not in _VALID_FINAL:
        raise ValueError(f"非法 final_status: {final_status}")
    row = (
        db.query(FissionVariant)
        .filter(FissionVariant.variant_id == variant_id,
                FissionVariant.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        return None
    row.qa_status = qa_status
    if final_status is not None:
        row.final_status = final_status
    db.commit()
    return _to_dict(row)


def _to_dict(v: FissionVariant) -> dict:
    def _j(s, default):
        return json.loads(s) if s else default
    return {
        "variant_id": v.variant_id,
        "fission_plan_id": v.fission_plan_id,
        "tenant_id": v.tenant_id,
        "group_type": v.group_type,
        "center_idea": v.center_idea,
        "segment_plan": _j(v.segment_plan, []),
        "skill_sequence": _j(v.skill_sequence, []),
        "asset_sequence": _j(v.asset_sequence, []),
        "output_requirements": _j(v.output_requirements, {}),
        "qa_expected": _j(v.qa_expected, {}),
        "qa_status": v.qa_status,
        "retry_count": v.retry_count,
        "max_retry": v.max_retry,
        "final_status": v.final_status,
        "output_video_id": v.output_video_id,
        "sort_order": v.sort_order,
    }
