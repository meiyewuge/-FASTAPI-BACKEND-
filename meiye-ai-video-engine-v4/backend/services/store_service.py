"""门店服务：在租户内按需创建/补齐门店（门店是 tenant 内 target，不拆 tenant）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import Store


def list_stores(db: Session, tenant_id: str) -> list[Store]:
    return db.query(Store).filter(Store.tenant_id == tenant_id).order_by(Store.id).all()


def ensure_stores(
    db: Session,
    tenant_id: str,
    count: int,
    city: str | None,
    industry: str | None,
) -> list[Store]:
    """保证该租户下至少有 count 个门店；不足则自动补齐占位门店。返回前 count 个。"""
    existing = list_stores(db, tenant_id)
    need = count - len(existing)
    label = f"{city or ''}{industry or '门店'}"
    for i in range(need):
        idx = len(existing) + i + 1
        s = Store(tenant_id=tenant_id, name=f"{label}{idx}", city=city, industry=industry)
        db.add(s)
        existing.append(s)
    db.flush()
    return existing[:count]
