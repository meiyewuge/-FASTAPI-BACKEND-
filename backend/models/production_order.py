"""生产单 + 镜头映射表（V4 P2A）。

production_orders：从 director_plan 生成的生产单（含 contract_version / asset_policy / fission_goal）。
shot_maps：镜头角色映射（pain/product/solution/result/brand/cta），含 tenant_id（多租户隔离）。

P2A 边界：只新增表，零改现有 schema；preview 不入库、create 落库；不触发火山、不写 videos。
"""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, func

from db import Base


class ProductionOrder(Base):
    __tablename__ = "production_orders"

    production_order_id = Column(String(40), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(32), nullable=True)
    brand_id = Column(String(40), nullable=True)
    product_id = Column(String(40), nullable=True)
    scenario = Column(String(32), nullable=True)   # product_seeding|brand_story|tutorial|comparison|review|event|testimony
    platform = Column(String(24), nullable=True)   # douyin|xiaohongshu|shipinhao|kuaishou
    ratio = Column(String(8), nullable=True)        # 9:16|16:9|1:1
    duration = Column(Integer, nullable=False, default=30)   # A台母视频目标秒数
    director_plan_id = Column(String(40), nullable=True)     # 引用 director_plans
    mother_video_ids = Column(Text, nullable=True)           # JSON array of video ids
    asset_pack_id = Column(String(40), nullable=True)        # 引用 asset_packs (P2C)
    asset_policy = Column(Text, nullable=True)               # JSON: 素材策略
    selected_assets = Column(Text, nullable=True)            # JSON array: 已选素材
    paid_asset_budget = Column(Float, nullable=False, default=0.0)
    asset_cost_estimate = Column(Float, nullable=False, default=0.0)
    skill_profile_id = Column(String(40), nullable=True)
    fission_goal = Column(Text, nullable=True)               # JSON: {target_count, ratio_per_source, max_outputs, output_seconds}
    qa_gates = Column(Text, nullable=True)                   # JSON array of gate names
    cost_policy = Column(Text, nullable=True)                # JSON: {b_track_api_cost, allow_llm_assist, compose_locked}
    contract_version = Column(String(16), nullable=False, default="1.0")
    status = Column(String(16), nullable=False, default="preview")  # preview|confirmed|producing|done|partial_done|failed
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_po_tenant", "tenant_id"),
        Index("idx_po_status", "status"),
        Index("idx_po_dp", "director_plan_id"),
    )


class ShotMap(Base):
    __tablename__ = "shot_maps"

    shot_id = Column(String(40), primary_key=True)
    production_order_id = Column(
        String(40), ForeignKey("production_orders.production_order_id"), nullable=False
    )
    tenant_id = Column(String(64), nullable=False)
    source_video_id = Column(Integer, nullable=True)
    source_kind = Column(String(16), nullable=False, default="mother")  # mother|upload|stock
    role = Column(String(16), nullable=False)                            # pain|product|solution|result|brand|cta
    start_time = Column(Float, nullable=True)
    end_time = Column(Float, nullable=True)
    text_content = Column(Text, nullable=True)
    visual_description = Column(Text, nullable=True)
    image_refs = Column(Text, nullable=True)         # JSON array: [{file_id, role}]
    confidence = Column(Float, nullable=False, default=0.0)
    qa_notes = Column(Text, nullable=True)           # JSON array of strings
    sort_order = Column(Integer, nullable=False, default=0)
    contract_version = Column(String(16), nullable=False, default="1.0")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_sm_po", "production_order_id"),
        Index("idx_sm_tenant", "tenant_id"),
        Index("idx_sm_role", "role"),
    )
