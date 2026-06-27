"""P2A 初始化迁移（V4 P2A）。

职责：
1. 创建 6 张新表（production_orders / shot_maps / fission_plans / fission_variants /
   qa_results / skill_registry）——含 tenant_id 字段与命名索引。
2. 幂等播种 12 条 skill_registry 种子数据（skill_id 精确锁定集合，见 §2.7）。

铁律 §9：只新增表，零改现有 schema。建表用 SQLAlchemy create_all（仅创建缺失表），
不 DROP、不 ALTER 任何现有表。可重复执行。

用法：
    cd backend && python -m migrations.p2a_init
（部署前请先按施工包 §6 备份 staging DB。）
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from db import Base, SessionLocal, engine
# 触发 6 张表的 ORM 定义注册到 Base.metadata
from models import (  # noqa: F401
    FissionPlan, FissionVariant, ProductionOrder, QaResult, ShotMap, SkillRegistry,
)
from services.skill_registry_service import CANONICAL_SKILL_IDS, seed_skills

P2A_TABLES = [
    "production_orders",
    "shot_maps",
    "fission_plans",
    "fission_variants",
    "qa_results",
    "skill_registry",
]


def run() -> dict:
    """执行迁移：建表 + 播种。返回结果摘要。"""
    # 1) 建表（create_all 只创建尚不存在的表，不动现有 schema）
    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    missing = [t for t in P2A_TABLES if t not in existing]
    if missing:
        raise RuntimeError(f"P2A 建表失败，缺失表: {missing}")

    # 2) 幂等播种 skill_registry
    db = SessionLocal()
    try:
        added = seed_skills(db)
        actual = {row[0] for row in db.execute(
            text("SELECT skill_id FROM skill_registry")
        ).fetchall()}
    finally:
        db.close()

    # 3) 精确集合校验（与 §2.7 CANONICAL_SKILL_IDS 完全一致）
    if actual != CANONICAL_SKILL_IDS:
        raise RuntimeError(
            f"skill_id 精确集合不一致: extra={actual - CANONICAL_SKILL_IDS}, "
            f"missing={CANONICAL_SKILL_IDS - actual}"
        )

    return {
        "tables_created": P2A_TABLES,
        "skills_added": added,
        "skills_total": len(actual),
        "skill_id_set_ok": True,
    }


if __name__ == "__main__":
    result = run()
    print("✅ P2A migration done:")
    for k, v in result.items():
        print(f"   {k}: {v}")
    sys.exit(0)
