"""P2B-B1 小批量真实执行 · run + run_item 表（V4 P2B-B1）。

只新增 2 张表，不改 P2A/P2B-A 表：
- p2b_execution_runs：一次小批量执行（绑定真实 source_video_id）。
- p2b_execution_run_items：每条 execution_plan 的真实落地结果。

均含 tenant_id（NOT NULL）+ tenant/status 索引；所有查询带 tenant 过滤。
真实执行受 ENABLE_P2B_REAL_EXECUTION + APP_ENV(staging) 双闸门控制；production 强制 403。
"""

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, func

from db import Base


class P2bExecutionRun(Base):
    __tablename__ = "p2b_execution_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(48), nullable=False, unique=True)
    tenant_id = Column(String(64), nullable=False)
    production_order_id = Column(String(40), nullable=False)
    fission_plan_id = Column(String(40), nullable=True)
    source_video_id = Column(Integer, nullable=False)         # 运行时绑定的真实源视频
    run_name = Column(String(128), nullable=True)
    run_type = Column(String(32), nullable=False, default="p2b_b1_small_batch")
    status = Column(String(16), nullable=False, default="preview")  # preview|running|done|partial_done|failed
    max_items = Column(Integer, nullable=False, default=3)
    requested_count = Column(Integer, nullable=False, default=0)
    completed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    cost_estimate = Column(Float, nullable=False, default=0.0)
    execute_allowed = Column(Integer, nullable=False, default=0)
    app_env = Column(String(16), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_pbr_tenant", "tenant_id"),
        Index("idx_pbr_po", "production_order_id"),
        Index("idx_pbr_status", "status"),
    )


class P2bExecutionRunItem(Base):
    __tablename__ = "p2b_execution_run_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(48), nullable=False, unique=True)
    run_id = Column(String(48), nullable=False)
    tenant_id = Column(String(64), nullable=False)
    execution_plan_id = Column(String(48), nullable=False)
    variant_id = Column(String(40), nullable=False)
    group_type = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default="pending")  # pending|running|done|failed|skipped
    video_id = Column(Integer, nullable=True)
    output_path = Column(String(512), nullable=True)
    error_message = Column(Text, nullable=True)
    rhythm_applied_json = Column(Text, nullable=True)
    transition_applied_json = Column(Text, nullable=True)
    subtitle_applied_json = Column(Text, nullable=True)
    highlight_card_applied_json = Column(Text, nullable=True)
    dedup_applied_json = Column(Text, nullable=True)
    cta_applied_json = Column(Text, nullable=True)
    duration = Column(Float, nullable=True)
    md5 = Column(String(64), nullable=True)
    qa_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_pri_run", "run_id"),
        Index("idx_pri_tenant", "tenant_id"),
        Index("idx_pri_ep", "execution_plan_id"),
        Index("idx_pri_status", "status"),
    )
