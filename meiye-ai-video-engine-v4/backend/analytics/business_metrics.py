"""业务指标推导（全部来自真实数据，零商业假设）。

指标定义（成本侧/产能侧，客观可复算）：
- 内容效率：每 1 元成本产出多少视频（videos_per_cost）
- 单视频均成本：total_cost / total_videos
- 裂变倍率：viral / mother
- 门店产能：每门店产出视频数 + 成本 + 效率
- 策略占比：各内容策略产出条数与成本占比
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from cost_engine import ledger
from cost_engine.pricing_model import unit_price
from models import Video


def overview(db: Session, tenant_id: str) -> dict:
    n_total = db.query(Video).filter(Video.tenant_id == tenant_id).count()
    n_mother = db.query(Video).filter(Video.tenant_id == tenant_id, Video.type == "mother").count()
    n_viral = db.query(Video).filter(Video.tenant_id == tenant_id, Video.type == "viral").count()
    cost = ledger.get_spend(db, tenant_id)
    return {
        "total_videos": n_total,
        "mother_videos": n_mother,
        "viral_videos": n_viral,
        "total_cost": round(cost, 4),
        "avg_cost_per_video": round(cost / n_total, 4) if n_total else 0.0,
        "videos_per_cost_unit": round(n_total / cost, 2) if cost else 0.0,
        "remix_multiplier": round(n_viral / n_mother, 2) if n_mother else 0.0,
    }


def by_store(db: Session, tenant_id: str) -> list[dict]:
    """门店产能/效率：在成本台账基础上加「每元产出视频数」。"""
    items = ledger.by_store(db, tenant_id)
    for it in items:
        c = it["cost"]
        it["videos_per_cost_unit"] = round(it["videos"] / c, 2) if c else 0.0
    return items


def by_strategy(db: Session, tenant_id: str) -> list[dict]:
    """各内容策略产出条数与成本占比（策略来自裂变视频 strategy 字段）。"""
    rows = (
        db.query(Video.strategy, func.count())
        .filter(Video.tenant_id == tenant_id, Video.type == "viral")
        .group_by(Video.strategy)
        .all()
    )
    counts: dict[str, int] = {(s or "未知"): int(n) for s, n in rows}

    clip_price = unit_price("video.remix.b")
    total = sum(counts.values()) or 1
    return [
        {
            "strategy": s,
            "videos": n,
            "share_pct": round(n / total * 100, 1),
            "est_cost": round(n * clip_price, 4),
        }
        for s, n in sorted(counts.items(), key=lambda x: -x[1])
    ]
