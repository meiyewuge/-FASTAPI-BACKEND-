"""租户表：SaaS 多租户 + 成本配额（熔断依据）。"""

from sqlalchemy import Column, DateTime, Float, String, func

from db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(64), primary_key=True)            # tenant_id
    name = Column(String(128), nullable=True)
    # 成本配额（货币单位）。spend 超过 quota 触发熔断。
    quota = Column(Float, nullable=False, default=100.0)
    created_at = Column(DateTime, server_default=func.now())
