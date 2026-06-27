"""技能注册表（V4 P2A，只读种子数据）。

铁律 §8：skill_registry 绝不存可执行命令 —— 只存 adapter 函数名（snake_case）+ 固定参数模板 +
JSON schema 校验。真实执行在 P2B 才技能化，P2A skill_executor 仅 mock/dry_validate。
"""

from sqlalchemy import Boolean, Column, DateTime, String, Text, func

from db import Base


class SkillRegistry(Base):
    __tablename__ = "skill_registry"

    skill_id = Column(String(48), primary_key=True)        # e.g. safe_trim_setpts_v1
    name = Column(String(128), nullable=False)             # 中文显示名
    category = Column(String(32), nullable=True)           # video_edit|text_overlay|qa_check|asset_process
    engine = Column(String(16), nullable=False, default="ffmpeg")
    adapter = Column(String(64), nullable=False)           # Python adapter 函数名（非 shell 命令），snake_case
    input_schema = Column(Text, nullable=True)             # JSON schema
    output_schema = Column(Text, nullable=True)            # JSON schema
    default_params = Column(Text, nullable=True)           # JSON: 固定参数模板
    business_use = Column(Text, nullable=True)
    platform_fit = Column(Text, nullable=True)             # JSON array
    risk_level = Column(String(8), nullable=False, default="low")
    qa_gates = Column(Text, nullable=True)                 # JSON array
    fallback = Column(String(48), nullable=True)           # fallback skill_id
    version = Column(String(16), nullable=False, default="v1")
    enabled = Column(Boolean, nullable=False, default=True)
    contract_version = Column(String(16), nullable=False, default="1.0")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
