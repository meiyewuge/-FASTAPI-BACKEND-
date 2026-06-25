"""导演稿表（V4 P0-B）。

compose preview 产出导演分镜 + 结构化提示词 + 图片角色，落库后供正式 compose 复用。
preview 阶段不调用火山、不扣费。每条记录三个版本号，便于追溯提示词效果。
"""

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from db import Base


class DirectorPlan(Base):
    __tablename__ = "director_plans"

    id = Column(String(40), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_phone = Column(String(32), nullable=True)
    prompt = Column(Text, nullable=True)
    style = Column(String(16), nullable=False, default="premium")
    ratio = Column(String(8), nullable=False, default="9:16")
    duration_seconds = Column(Integer, nullable=False, default=15)
    resolution = Column(String(8), nullable=False, default="1080p")
    director_json = Column(Text, nullable=True)            # 分镜数组 JSON
    seedance_text_prompt = Column(Text, nullable=True)     # T1-T5 组装后的 content[0].text
    image_roles_json = Column(Text, nullable=True)         # [{file_id, role, url}]
    # 模板版本（可追溯）
    director_prompt_version = Column(String(32), nullable=False, default="director_prompt_v1")
    style_preset_version = Column(String(32), nullable=False, default="style_preset_v1")
    negative_words_version = Column(String(32), nullable=False, default="beauty_safe_v1")
    estimated_cost = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), nullable=False, default="preview")  # preview|consumed
    created_at = Column(DateTime, server_default=func.now())
