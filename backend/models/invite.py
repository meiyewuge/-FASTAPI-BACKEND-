"""邀请码表（Patch4）。无邀请码不得登录。"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from db import Base


class InviteCode(Base):
    __tablename__ = "invite_codes"

    code = Column(String(32), primary_key=True)
    tenant_id = Column(String(64), nullable=True)   # 绑定租户；空=按手机号建租户
    phone = Column(String(32), nullable=True)       # Patch4.1：首次登录绑定手机号（专属登录码可重复登录）
    active = Column(Boolean, nullable=False, default=True)
    max_uses = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
