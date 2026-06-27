"""裂变计划 + 裂变变体表（V4 P2A）。

fission_plans：生产单 → 6 组裂变计划。
fission_variants：每条裂变施工单（segment_plan / skill_sequence / output_requirements / qa_status），
含 tenant_id（多租户隔离）。

P2A 边界：preview 不入库、不执行真实裂变、不调用 remixer、不写 videos；output_video_id 在 P2B 才写。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func

from db import Base


class FissionPlan(Base):
    __tablename__ = "fission_plans"

    fission_plan_id = Column(String(40), primary_key=True)
    production_order_id = Column(
        String(40), ForeignKey("production_orders.production_order_id"), nullable=False
    )
    tenant_id = Column(String(64), nullable=False)
    source_video_ids = Column(Text, nullable=True)   # JSON array
    target_count = Column(Integer, nullable=False, default=30)
    groups = Column(Text, nullable=True)             # JSON array: [{group_type, center_idea, count}]
    variant_ids = Column(Text, nullable=True)        # JSON array of variant_id references
    required_skills = Column(Text, nullable=True)    # JSON array of skill_id
    required_assets = Column(Text, nullable=True)    # JSON: {asset_pack_id, needs, stock_plan}
    asset_summary = Column(Text, nullable=True)      # JSON: {user_uploads, brand_pack, free_stock, paid_stock}
    qa_gates = Column(Text, nullable=True)           # JSON array
    contract_version = Column(String(16), nullable=False, default="1.0")
    status = Column(String(16), nullable=False, default="preview")  # preview|executing|done|partial_done|failed
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_fp_po", "production_order_id"),
        Index("idx_fp_tenant", "tenant_id"),
        Index("idx_fp_status", "status"),
    )


class FissionVariant(Base):
    __tablename__ = "fission_variants"

    variant_id = Column(String(40), primary_key=True)
    fission_plan_id = Column(
        String(40), ForeignKey("fission_plans.fission_plan_id"), nullable=False
    )
    tenant_id = Column(String(64), nullable=False)
    group_type = Column(String(32), nullable=True)   # pain_first|selling_first|result_close|brand_double|same_source|reverse
    center_idea = Column(Text, nullable=True)
    segment_plan = Column(Text, nullable=True)        # JSON array: [{shot_id, src_video_id, in, out, role}]
    skill_sequence = Column(Text, nullable=True)      # JSON array: [{skill_id, params}]
    asset_sequence = Column(Text, nullable=True)      # JSON array: [{asset_id, type, role}]
    subtitle_plan = Column(Text, nullable=True)       # JSON: {style, lines}
    transition_plan = Column(Text, nullable=True)     # JSON: {type, duration, max_effects}
    output_requirements = Column(Text, nullable=True) # JSON: {ratio, fps, reencode, target_seconds, cost}
    qa_expected = Column(Text, nullable=True)         # JSON: {pts_monotonic, playable_to_end, duration_in_range}
    qa_status = Column(String(16), nullable=False, default="pending")  # pending|pass|warn|fail
    retry_count = Column(Integer, nullable=False, default=0)
    max_retry = Column(Integer, nullable=False, default=2)
    final_status = Column(String(16), nullable=True)  # pass|failed|skipped
    output_video_id = Column(Integer, nullable=True)  # 成功时关联 videos.id（P2B 才写）
    contract_version = Column(String(16), nullable=False, default="1.0")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_fv_fp", "fission_plan_id"),
        Index("idx_fv_tenant", "tenant_id"),
        Index("idx_fv_group", "group_type"),
        Index("idx_fv_qa", "qa_status"),
    )
