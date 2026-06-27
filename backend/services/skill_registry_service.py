"""技能注册表服务（V4 P2A）。

唯一真值源：P2A_SKILL_REGISTRY_SEED / CANONICAL_SKILL_IDS（与施工包 §2.7 完全一致）。
migration seed、skill_executor 白名单、director_layer skill_sequence、API、tests 全部以此为准。

铁律 §8：注册表只存 adapter 函数名（snake_case），绝不存可执行 shell 命令。
P2A 仅只读（列表 + 种子），不开放写接口。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models import SkillRegistry

# ===== P2A SKILL_ID 锁定集合（V1.2 精确定义，全文档唯一真值源）=====
# 规则：skill_id = 动词_名词_..._vN（snake_case + 版本后缀）
# 规则：adapter   = skill_id 去 _vN 后缀 + _adapter
# 字段顺序：(skill_id, name, category, adapter, risk_level)
P2A_SKILL_REGISTRY_SEED = [
    ("safe_trim_setpts_v1",        "安全切片(trim+setpts)",        "video_edit",   "safe_trim_setpts_adapter",        "low"),
    ("normalize_video_v1",         "规范化视频(1080x1920/30fps)",  "video_edit",   "normalize_video_adapter",         "low"),
    ("safe_concat_v1",             "安全拼接(重编码)",             "video_edit",   "safe_concat_adapter",             "low"),
    ("playback_validate_v1",       "播放验证(解码到结尾)",          "qa_check",     "playback_validate_adapter",       "low"),
    ("probe_video_v1",             "视频探测(ffprobe)",            "qa_check",     "probe_video_adapter",             "low"),
    ("shot_role_labeler_v1",       "镜头角色标注",                "video_edit",   "shot_role_labeler_adapter",       "low"),
    ("mother_segment_mapper_v1",   "母视频分段映射",               "video_edit",   "mother_segment_mapper_adapter",   "low"),
    ("fission_strategy_planner_v1", "裂变策略规划",                "video_edit",   "fission_strategy_planner_adapter", "low"),
    ("text_card_insert_v1",        "文字卡片插入",                "text_overlay", "text_card_insert_adapter",        "medium"),
    ("product_image_insert_v1",    "产品图插入",                  "text_overlay", "product_image_insert_adapter",    "medium"),
    ("subtitle_brand_style_v1",    "品牌风格字幕",                "text_overlay", "subtitle_brand_style_adapter",    "low"),
    ("md5_duplicate_check_v1",     "MD5去重检测",                 "qa_check",     "md5_duplicate_check_adapter",     "low"),
]

# 精确集合（用于全链路校验：DB 中的 skill_id 集合必须与此完全相等）
CANONICAL_SKILL_IDS = {
    "safe_trim_setpts_v1",
    "normalize_video_v1",
    "safe_concat_v1",
    "playback_validate_v1",
    "probe_video_v1",
    "shot_role_labeler_v1",
    "mother_segment_mapper_v1",
    "fission_strategy_planner_v1",
    "text_card_insert_v1",
    "product_image_insert_v1",
    "subtitle_brand_style_v1",
    "md5_duplicate_check_v1",
}


def seed_skills(db: Session) -> int:
    """幂等播种 12 条 canonical 技能。已存在则补齐缺失的，返回新增条数。"""
    existing = {s.skill_id for s in db.query(SkillRegistry.skill_id).all()}
    added = 0
    for skill_id, name, category, adapter, risk_level in P2A_SKILL_REGISTRY_SEED:
        if skill_id in existing:
            continue
        db.add(SkillRegistry(
            skill_id=skill_id, name=name, category=category, engine="ffmpeg",
            adapter=adapter, risk_level=risk_level, version="v1", enabled=True,
            contract_version="1.0",
        ))
        added += 1
    if added:
        db.commit()
    return added


def _to_dict(s: SkillRegistry) -> dict:
    return {
        "skill_id": s.skill_id,
        "name": s.name,
        "category": s.category,
        "engine": s.engine,
        "adapter": s.adapter,
        "default_params": json.loads(s.default_params) if s.default_params else {},
        "business_use": s.business_use,
        "platform_fit": json.loads(s.platform_fit) if s.platform_fit else [],
        "risk_level": s.risk_level,
        "qa_gates": json.loads(s.qa_gates) if s.qa_gates else [],
        "fallback": s.fallback,
        "version": s.version,
        "enabled": bool(s.enabled),
        "contract_version": s.contract_version,
    }


def list_skills(db: Session, enabled_only: bool = False) -> list[dict]:
    """技能列表（只读）。"""
    q = db.query(SkillRegistry)
    if enabled_only:
        q = q.filter(SkillRegistry.enabled.is_(True))
    rows = q.order_by(SkillRegistry.skill_id.asc()).all()
    return [_to_dict(r) for r in rows]


def get_skill(db: Session, skill_id: str) -> dict | None:
    s = db.get(SkillRegistry, skill_id)
    return _to_dict(s) if s else None
