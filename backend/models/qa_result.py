"""质检结果表（V4 P2A）。

复用 b_engine/qa_checks.py 的 4 道 hard gate（duration/pts/playable/md5），
并预留 license / brand / subtitle / platform_risk 等 P2B soft gate 字段。

P2A 仅建表（结构预留），不在 preview 路径写入。
"""

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, func,
)

from db import Base


class QaResult(Base):
    __tablename__ = "qa_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)
    production_order_id = Column(String(40), nullable=True)
    variant_id = Column(String(40), ForeignKey("fission_variants.variant_id"), nullable=True)
    tenant_id = Column(String(64), nullable=True)
    duration_ok = Column(Boolean, nullable=True)
    pts_ok = Column(Boolean, nullable=True)
    playable_ok = Column(Boolean, nullable=True)
    md5_duplicate = Column(Boolean, nullable=True)
    perceptual_similarity = Column(Float, nullable=True)
    brand_presence = Column(Boolean, nullable=True)
    subtitle_readability = Column(String(8), nullable=True)   # ok|warn|fail
    license_ok = Column(Boolean, nullable=False, default=True)
    license_claim_ok = Column(Boolean, nullable=False, default=True)
    platform_risk = Column(String(8), nullable=True)          # low|medium|high
    retry_count = Column(Integer, nullable=False, default=0)
    final_status = Column(String(8), nullable=True)           # pass|warn|fail
    qa_logs = Column(Text, nullable=True)                     # JSON array: [{gate, result, detail}]
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_qr_video", "video_id"),
        Index("idx_qr_variant", "variant_id"),
        Index("idx_qr_status", "final_status"),
    )
