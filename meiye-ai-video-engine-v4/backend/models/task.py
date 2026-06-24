"""任务表：A台/B台 异步任务，含 retry 计数。"""

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from db import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(40), primary_key=True)               # uuid hex
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    type = Column(String(8), nullable=False)                # a | b
    status = Column(String(16), nullable=False, default="pending")  # pending|running|done|failed
    progress = Column(Float, nullable=False, default=0.0)
    payload = Column(Text, nullable=True)                   # JSON 输入
    result = Column(Text, nullable=True)                    # JSON 产出（video ids/urls）
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
