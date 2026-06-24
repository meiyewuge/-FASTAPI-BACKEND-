"""门店表（store）—— 租户内部的业务对象/任务维度，**不是租户**。

关系：Tenant 1 → N Store。门店是「任务对象」，不是「租户」。
"""

from sqlalchemy import Column, DateTime, Integer, String, func

from db import Base


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    name = Column(String(128), nullable=False)
    city = Column(String(64), nullable=True)
    industry = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
