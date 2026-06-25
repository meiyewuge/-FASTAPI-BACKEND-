"""管理员/角色表（Patch6）：管理员身份与发码权限体系。

role：
- super_admin：初始超级管理员（吴哥本人），拥有全部权限，可授权他人。
- invite_admin：发码员，仅可生成/查看/作废邀请码，不能授权他人。
- user：普通用户（不入本表，缺省即 user）。
"""

from sqlalchemy import Column, DateTime, String, func

from db import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    phone = Column(String(32), primary_key=True)
    role = Column(String(16), nullable=False, default="user")   # super_admin | invite_admin
    status = Column(String(16), nullable=False, default="active")  # active | disabled
    created_by = Column(String(32), nullable=True)              # 授权人 phone（bootstrap 为 system）
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
