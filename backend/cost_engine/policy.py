"""熔断策略：租户配额与预检。orchestrator 只报「用量」，价格与放行判断都在此。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cost_engine.pricing_model import price
from models import Tenant


class QuotaExceeded(Exception):
    """成本超过租户配额，熔断。"""


def get_or_create_tenant(db: Session, tenant_id: str) -> Tenant:
    t = db.get(Tenant, tenant_id)
    if t is None:
        t = Tenant(id=tenant_id, name=tenant_id)
        db.add(t)
        db.flush()
    return t


def ensure_budget(db: Session, tenant_id: str, api_name: str, units: float) -> None:
    """投递前预检：已花 + 本次预估（按计价模型） > 配额 → 熔断。"""
    from cost_engine.ledger import get_spend  # 延迟导入避免循环

    estimated = price(api_name, units)
    tenant = get_or_create_tenant(db, tenant_id)
    spend = get_spend(db, tenant_id)
    if spend + estimated > tenant.quota:
        raise QuotaExceeded(
            f"租户 {tenant_id} 成本熔断：已用 {spend:.2f} + 预估 {estimated:.2f} "
            f"超过配额 {tenant.quota:.2f}"
        )
