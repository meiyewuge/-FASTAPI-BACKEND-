"""成本系统：记录 + 按 tenant 统计 + 配额熔断（enforcement）。"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import CostRecord, Tenant


class QuotaExceeded(Exception):
    """成本超过租户配额，熔断。"""


def get_or_create_tenant(db: Session, tenant_id: str) -> Tenant:
    t = db.get(Tenant, tenant_id)
    if t is None:
        t = Tenant(id=tenant_id, name=tenant_id)
        db.add(t)
        db.flush()
    return t


def get_spend(db: Session, tenant_id: str) -> float:
    total = (
        db.query(func.coalesce(func.sum(CostRecord.amount), 0.0))
        .filter(CostRecord.tenant_id == tenant_id)
        .scalar()
    )
    return float(total or 0.0)


def ensure_budget(db: Session, tenant_id: str, estimated: float) -> None:
    """熔断：若 已花费 + 预估 > 配额，拒绝。"""
    tenant = get_or_create_tenant(db, tenant_id)
    spend = get_spend(db, tenant_id)
    if spend + estimated > tenant.quota:
        raise QuotaExceeded(
            f"租户 {tenant_id} 成本熔断：已用 {spend:.2f} + 预估 {estimated:.2f} "
            f"超过配额 {tenant.quota:.2f}"
        )


def record(
    db: Session,
    tenant_id: str,
    api_name: str,
    units: float,
    amount: float,
    task_id: str | None = None,
    provider: str = "",
    store_id: int | None = None,
) -> CostRecord:
    rec = CostRecord(
        tenant_id=tenant_id,
        store_id=store_id,
        api_name=api_name,
        provider=provider,
        units=units,
        amount=amount,
        task_id=task_id,
    )
    db.add(rec)
    db.flush()
    return rec


def summary(db: Session, tenant_id: str) -> dict:
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
