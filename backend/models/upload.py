"""上传文件表（Patch2）。file_id 对外暴露，local_path 仅后端用。"""

from sqlalchemy import Column, DateTime, Integer, String, func

from db import Base


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(40), nullable=False, unique=True, index=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    file_type = Column(String(16), nullable=False)          # image | text | video
    file_name = Column(String(255), nullable=True)          # 原始名（已脱危险字符）
    file_size = Column(Integer, nullable=False, default=0)
    local_path = Column(String(512), nullable=True)
    file_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
