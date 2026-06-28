"""P2B-B1 初始化迁移（V4 P2B-B1）。

只新增 2 张表 p2b_execution_runs / p2b_execution_run_items（含 tenant_id + 索引）。
不改 P2A/P2B-A 表。create_all 仅建缺失表，可重复执行。

用法：cd backend && python -m migrations.p2b_b1_init
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect

from db import Base, engine
from models import P2bExecutionRun, P2bExecutionRunItem  # noqa: F401

P2B_B1_TABLES = ["p2b_execution_runs", "p2b_execution_run_items"]
# 不可被本迁移改动的既有收口表（仅做存在性核对）
LOCKED_TABLES = ["execution_plans", "skill_executions", "production_orders",
                 "shot_maps", "fission_plans", "fission_variants"]


def run() -> dict:
    insp = inspect(engine)
    before = set(insp.get_table_names())
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    after = set(insp.get_table_names())

    missing = [t for t in P2B_B1_TABLES if t not in after]
    if missing:
        raise RuntimeError(f"P2B-B1 建表失败，缺失: {missing}")

    return {
        "tables_created": [t for t in P2B_B1_TABLES if t not in before],
        "runs_indexes": sorted(ix["name"] for ix in insp.get_indexes("p2b_execution_runs")),
        "items_indexes": sorted(ix["name"] for ix in insp.get_indexes("p2b_execution_run_items")),
        "locked_tables_present": [t for t in LOCKED_TABLES if t in after],
    }


if __name__ == "__main__":
    result = run()
    print("✅ P2B-B1 migration done:")
    for k, v in result.items():
        print(f"   {k}: {v}")
    sys.exit(0)
