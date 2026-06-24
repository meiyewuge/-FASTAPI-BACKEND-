"""台账：成本查询与统计（只读）。"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import CostRecord, Store


def by_store(db: Session, tenant_id: str) -> list[dict]:
    """按门店聚合成本（真实台账，不含任何收入/ROI 假设）。"""
    rows = (
        db.query(
            CostRecord.store_id,
            func.count().label("records"),
            func.coalesce(func.sum(CostRecord.units), 0.0),
            func.coalesce(func.sum(CostRecord.duration), 0.0),
            func.coalesce(func.sum(CostRecord.amount), 0.0),
        )
        .filter(CostRecord.tenant_id == tenant_id)
        .group_by(CostRecord.store_id)
        .all()
    )
    names = {
        s.id: s.name
        for s in db.query(Store).filter(Store.tenant_id == tenant_id).all()
    }
    return [
        {
            "store_id": sid,
            "store_name": names.get(sid),
            "records": int(n),
            "videos": int(units),
            "duration_sec": round(float(dur), 1),
            "cost": round(float(amt), 4),
        }
        for sid, n, units, dur, amt in rows
    ]


def by_provider(db: Session, tenant_id: str) -> list[dict]:
    rows = (
        db.query(
            CostRecord.provider,
            func.count(),
            func.coalesce(func.sum(CostRecord.amount), 0.0),
        )
        .filter(CostRecord.tenant_id == tenant_id)
        .group_by(CostRecord.provider)
        .all()
    )
    return [{"provider": p, "records": int(n), "cost": round(float(a), 4)} for p, n, a in rows]


def get_spend(db: Session, tenant_id: str) -> float:
    total = (
        db.query(func.coalesce(func.sum(CostRecord.amount), 0.0))
        .filter(CostRecord.tenant_id == tenant_id)
        .scalar()
    )
    return float(total or 0.0)


def summary(db: Session, tenant_id: str) -> dict:
    from cost_engine.policy import get_or_create_tenant  # 延迟导入避免循环

    tenant = get_or_create_tenant(db, tenant_id)
    spend = get_spend(db, tenant_id)
    by_api = dict(
        db.query(CostRecord.api_name, func.coalesce(func.sum(CostRecord.amount), 0.0))
        .filter(CostRecord.tenant_id == tenant_id)
        .group_by(CostRecord.api_name)
        .all()
    )
    return {
        "tenant_id": tenant_id,
        "quota": tenant.quota,
        "spend": round(spend, 4),
        "remaining": round(tenant.quota - spend, 4),
        "by_api": {k: round(float(v), 4) for k, v in by_api.items()},
    }
