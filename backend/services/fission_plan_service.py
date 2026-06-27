"""裂变计划服务（V4 P2A）。

preview：production_order_id → fission_plan preview（30 条 variant，每条含 tenant_id）。
不入库、0 成本、不执行真实裂变、不调 remixer、不触发火山、不写 videos。
execute → P2B。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import ProductionOrder, ShotMap
from services import director_layer_service, production_order_service


def build_preview(db: Session, tenant_id: str, production_order_id: str) -> dict | None:
    """生产单 → 裂变计划 preview。生产单不存在/越权 → None。"""
    order = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.production_order_id == production_order_id,
                ProductionOrder.tenant_id == tenant_id)
        .first()
    )
    if order is None:
        return None
    shot_rows = (
        db.query(ShotMap)
        .filter(ShotMap.production_order_id == production_order_id,
                ShotMap.tenant_id == tenant_id)
        .order_by(ShotMap.sort_order.asc())
        .all()
    )
    shots = [production_order_service._shot_to_dict(s) for s in shot_rows]
    return director_layer_service.build_fission_plan(db, tenant_id, order, shots, preview=True)
