"""成本记录表：按 tenant_id 维度记录每次 API 调用成本（成本系统/熔断依据）。"""

from sqlalchemy import Column, DateTime, Float, Integer, String, func

from db import Base


class CostRecord(Base):
    __tablename__ = "cost_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    store_id = Column(Integer, nullable=True, index=True)   # 门店归因
    api_name = Column(String(64), nullable=False)           # 如 video.generate.a / video.remix.b
    provider = Column(String(64), nullable=False, default="")  # 实际 provider，如 volcano_seedance / mock
    task_id = Column(String(40), nullable=True, index=True)
    units = Column(Float, nullable=False, default=0.0)      # 调用量（条/秒/token）
    amount = Column(Float, nullable=False, default=0.0)     # 金额
    duration = Column(Float, nullable=True)                 # 视频时长（秒）
    created_at = Column(DateTime, server_default=func.now())
