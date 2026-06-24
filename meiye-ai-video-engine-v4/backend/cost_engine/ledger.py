"""台账：成本查询与统计（只读）。"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import CostRecord


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
