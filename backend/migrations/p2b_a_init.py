"""P2B-A 初始化迁移（V4 P2B-A · Dry-run）。

职责：只新增 2 张表 execution_plans / skill_executions（含 tenant_id + 索引 +
幂等唯一索引 idx_ep_idempotent）。**不改 P2A 表、不写 P2A skill_registry。**

铁律：create_all 仅创建缺失表，不 DROP/ALTER 任何现有表。可重复执行。

用法：cd backend && python -m migrations.p2b_a_init
（部署前请先备份 staging DB。）
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect

from db import Base, engine
# 触发 2 张表 + （间接）P2A/P1.1 全部 ORM 注册
from models import ExecutionPlan, SkillExecution  # noqa: F401

P2B_TABLES = ["execution_plans", "skill_executions"]

# P2A 收口表（迁移前后必须存在且数量不变，作为「不改 P2A」证据）
P2A_TABLES = ["production_orders", "shot_maps", "fission_plans",
              "fission_variants", "qa_results", "skill_registry"]


def run() -> dict:
    insp = inspect(engine)
    before = set(insp.get_table_names())

    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    after = set(insp.get_table_names())
    missing = [t for t in P2B_TABLES if t not in after]
    if missing:
        raise RuntimeError(f"P2B-A 建表失败，缺失: {missing}")

    # 唯一索引 idx_ep_idempotent 必须存在
    ep_indexes = {ix["name"] for ix in insp.get_indexes("execution_plans")}
    if "idx_ep_idempotent" not in ep_indexes:
        raise RuntimeError(f"缺少幂等唯一索引 idx_ep_idempotent，实际: {sorted(ep_indexes)}")

    return {
        "tables_created": [t for t in P2B_TABLES if t not in before],
        "execution_plans_indexes": sorted(ep_indexes),
        "skill_executions_indexes": sorted(ix["name"] for ix in insp.get_indexes("skill_executions")),
        "p2a_tables_present": [t for t in P2A_TABLES if t in after],
    }


if __name__ == "__main__":
    result = run()
    print("✅ P2B-A migration done:")
    for k, v in result.items():
        print(f"   {k}: {v}")
    sys.exit(0)
