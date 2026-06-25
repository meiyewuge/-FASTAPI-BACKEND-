"""成本流水台账（V4 P0-A，BUG-2）。

CostRecord 是「最终成本汇总」；CostLedger 是「事件流水」——记录每一次
estimate/precharge/refund/final_adjust，可按 task_id + provider_job_id 全程追踪，
杜绝暗烧（线程卡死但火山已扣费）与 recovery 重复预扣。
"""

from sqlalchemy import Column, DateTime, Float, Integer, String, func

from db import Base


class CostLedger(Base):
    __tablename__ = "cost_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(40), nullable=True, index=True)
    provider_job_id = Column(String(64), nullable=True, index=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_phone = Column(String(32), nullable=True)
    model = Column(String(64), nullable=True)
    resolution = Column(String(8), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    request_type = Column(String(32), nullable=True)        # compose|a_generate|b_remix
    estimated_amount = Column(Float, nullable=False, default=0.0)
    precharged_amount = Column(Float, nullable=False, default=0.0)
    actual_amount = Column(Float, nullable=False, default=0.0)
    event_type = Column(String(16), nullable=False)         # estimate|precharge|refund|final_adjust
    status = Column(String(16), nullable=False, default="ok")
    created_at = Column(DateTime, server_default=func.now())
