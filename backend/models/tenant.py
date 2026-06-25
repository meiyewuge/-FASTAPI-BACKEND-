"""租户表：SaaS 多租户 + 成本配额（熔断依据）。"""

from sqlalchemy import Column, DateTime, Float, Integer, String, func

from db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(64), primary_key=True)            # tenant_id
    name = Column(String(128), nullable=True)
    # 成本配额（货币单位）。spend 超过 quota 触发熔断。
    quota = Column(Float, nullable=False, default=100.0)
    # Patch5：订阅/试用（暂不接支付）
    # subscription_status: trial(试用) | active(已订阅) | expired(到期)
    subscription_status = Column(String(16), nullable=False, default="trial")
    # 试用余量：仅 A台（母视频生成）扣减，B台裂变不扣
    trial_remaining = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime, server_default=func.now())
