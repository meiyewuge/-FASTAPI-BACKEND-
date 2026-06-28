"""执行计划 + 技能执行记录表（V4 P2B-A · Dry-run）。

只新增 2 张表，不改 P2A 已收口表：
- execution_plans：30 条执行计划，持久化 7 个核心对象 JSON（explain 必须来自持久化数据）。
- skill_executions：技能执行记录（P2B-A 仅 planned，不执行）。

硬锁（吴哥施工指令）：
- 两表均含 tenant_id（NOT NULL）+ tenant 索引，所有查询带 tenant_id 过滤。
- plan_version 默认 'p2b_a_v1'；唯一索引 idx_ep_idempotent
  (tenant_id, production_order_id, plan_version, variant_id) 保证重复 confirm 幂等。
- execute_allowed 始终 0、cost_estimate 始终 0（P2B-A 不执行）。
"""

from sqlalchemy import (
    Column, DateTime, Float, Index, Integer, String, Text, func,
)

from db import Base


class ExecutionPlan(Base):
    __tablename__ = "execution_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_plan_id = Column(String(48), nullable=False, unique=True)
    tenant_id = Column(String(64), nullable=False)
    production_order_id = Column(String(40), nullable=False)
    fission_plan_id = Column(String(40), nullable=True)        # 可选
    variant_id = Column(String(40), nullable=False)
    plan_version = Column(String(16), nullable=False, default="p2b_a_v1")

    # 差异化参数
    group_type = Column(String(32), nullable=False)            # 痛点优先/卖点优先/...
    highlight_focus = Column(String(32), nullable=False)       # 痛点突出/卖点突出/...
    visual_style = Column(String(32), nullable=False)          # 电影感/时尚感/...

    # 技能链
    skill_chain = Column(Text, nullable=False)                 # JSON: [{skill_id, display_name}]
    skill_params = Column(Text, nullable=False)                # JSON: {skill_id: params}

    # 7 个核心对象 JSON 持久化（explain 必须来自这些字段，不依赖内存）
    creative_brief_json = Column(Text, nullable=True)
    theme_kernel_json = Column(Text, nullable=False)
    asset_manifest_json = Column(Text, nullable=True)
    mother_video_plan_json = Column(Text, nullable=True)
    fission_intent_json = Column(Text, nullable=True)
    variant_plan_json = Column(Text, nullable=False)

    # 6 个工艺计划冗余字段（便于直接查询；已收敛在 variant_plan_json 内）
    rhythm_plan = Column(Text, nullable=True)
    transition_plan = Column(Text, nullable=True)
    subtitle_plan = Column(Text, nullable=True)
    highlight_card_plan = Column(Text, nullable=True)
    uniqueness_plan = Column(Text, nullable=True)

    # 状态（锁定机制收敛到 status：preview→confirmed→locked）
    status = Column(String(16), nullable=False, default="preview")
    confirmed_at = Column(String(40), nullable=True)
    locked_at = Column(String(40), nullable=True)
    locked_by = Column(String(40), nullable=True)

    # 费用与执行控制（P2B-A 始终 0 / false）
    cost_estimate = Column(Float, nullable=False, default=0.0)
    execute_allowed = Column(Integer, nullable=False, default=0)

    craft_explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # 幂等唯一索引：同 (tenant, 生产单, 版本, variant) 不可重复 → confirm 幂等
        Index(
            "idx_ep_idempotent",
            "tenant_id", "production_order_id", "plan_version", "variant_id",
            unique=True,
        ),
        Index("idx_ep_tenant", "tenant_id"),
        Index("idx_ep_po", "production_order_id"),
        Index("idx_ep_fp", "fission_plan_id"),
        Index("idx_ep_status", "status"),
    )


class SkillExecution(Base):
    __tablename__ = "skill_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(48), nullable=False, unique=True)
    tenant_id = Column(String(64), nullable=False)
    execution_plan_id = Column(String(48), nullable=False)
    variant_id = Column(String(40), nullable=False)
    skill_id = Column(String(48), nullable=False)
    skill_layer = Column(String(8), nullable=False, default="L2")

    input_payload = Column(Text, nullable=True)               # JSON
    output_payload = Column(Text, nullable=True)              # JSON（P2B-A 存计划）

    status = Column(String(16), nullable=False, default="pending")  # pending|planned|done|failed
    started_at = Column(String(40), nullable=True)
    completed_at = Column(String(40), nullable=True)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_se_tenant", "tenant_id"),
        Index("idx_se_ep", "execution_plan_id"),
        Index("idx_se_variant", "variant_id"),
        Index("idx_se_skill", "skill_id"),
    )
