"""记账：写入一条成本记录。金额由计价模型统一换算。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cost_engine.pricing_model import price
from models import CostRecord


def record(
    db: Session,
    tenant_id: str,
    api_name: str,
    units: float,
    task_id: str | None = None,
    provider: str = "",
    store_id: int | None = None,
    duration: float | None = None,
) -> CostRecord:
    rec = CostRecord(
        tenant_id=tenant_id,
        store_id=store_id,
        api_name=api_name,
        provider=provider,
        units=units,
        amount=price(api_name, units, duration),
        task_id=task_id,
        duration=duration,
    )
    db.add(rec)
    db.flush()
    return rec
