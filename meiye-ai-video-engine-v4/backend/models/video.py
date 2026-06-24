"""视频表：母视频(mother) 与 裂变视频(viral) 共用，按 tenant_id 隔离。"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from db import Base


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    store_id = Column(Integer, nullable=True, index=True)   # 归因到门店（可空）
    type = Column(String(16), nullable=False)               # mother | viral
    title = Column(String(255), nullable=True)
    source_video_id = Column(Integer, nullable=True)        # 裂变视频指向母视频
    status = Column(String(16), nullable=False, default="ready")
    download_url = Column(String(512), nullable=True)
    share_url = Column(String(512), nullable=True)
    meta = Column(Text, nullable=True)                      # JSON：脚本/分镜/改动等
    created_at = Column(DateTime, server_default=func.now())
