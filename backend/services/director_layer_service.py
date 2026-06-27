"""导演层服务（V4 P2A）。

production_order + shot_maps → fission_plan：按 6 种 group_type 各 5 条，共 30 条 variant。
每条 variant：
- segment_plan：从 shot_maps 按 role 选镜头
- skill_sequence：只使用 §2.7 的 12 条 canonical skill_id（经 skill_executor 白名单校验）
- output_requirements：[25,35] 重编码、cost=0
- 必填 tenant_id

P2A 仅 preview（不入库、不执行真实裂变、不调 remixer、不触发火山、不写 videos）。
execute 模式 → P2B。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from models import ProductionOrder, ShotMap
from services import skill_executor

# 6 种 group_type → (中文 center_idea, role 序列)
GROUP_DEFS = [
    ("pain_first",    "痛点前置→卖点→品牌收束", ["pain", "product", "brand"]),
    ("selling_first", "卖点前置→痛点→品牌收束", ["product", "pain", "brand"]),
    ("result_close",  "痛点→效果收束→品牌",     ["pain", "result", "brand"]),
    ("brand_double",  "品牌双定→产品→品牌",     ["brand", "product", "brand"]),
    ("same_source",   "同源前后对比",            ["pain", "product", "result"]),
    ("reverse",       "倒叙：品牌→痛点→产品",    ["brand", "pain", "product"]),
]

VARIANTS_PER_GROUP = 5
TARGET_SECONDS = [25, 35]

# 各 group 在基础链路上额外叠加的 overlay 技能（均为 canonical skill_id）
_GROUP_EXTRA_SKILLS = {
    "pain_first":    ["text_card_insert_v1"],
    "selling_first": ["product_image_insert_v1"],
    "result_close":  ["text_card_insert_v1"],
    "brand_double":  ["product_image_insert_v1"],
    "same_source":   [],
    "reverse":       ["text_card_insert_v1"],
}


def _pick_shot(shots: list[dict], role: str, offset: int) -> dict | None:
    """按 role 选镜头；同 role 多条时按 offset 轮转；无该 role 时全局兜底。"""
    same = [s for s in shots if s.get("role") == role]
    pool = same or shots
    if not pool:
        return None
    return pool[offset % len(pool)]


def _segment_plan(shots: list[dict], roles: list[str], variant_idx: int) -> list[dict]:
    seg = []
    for j, role in enumerate(roles):
        sh = _pick_shot(shots, role, variant_idx + j)
        if sh is None:
            continue
        seg.append({
            "shot_id": sh.get("shot_id"),
            "src_video_id": sh.get("source_video_id"),
            "in": sh.get("start_time"),
            "out": sh.get("end_time"),
            "role": role,
        })
    return seg


def _skill_sequence(group_type: str) -> list[dict]:
    """组装 skill_sequence（全部来自 12 条 canonical skill_id）。"""
    seq = [
        {"skill_id": "shot_role_labeler_v1", "params": {}},
        {"skill_id": "mother_segment_mapper_v1", "params": {}},
        {"skill_id": "fission_strategy_planner_v1", "params": {"group_type": group_type}},
        {"skill_id": "safe_trim_setpts_v1", "params": {"reencode": True}},
        {"skill_id": "normalize_video_v1", "params": {"w": 1080, "h": 1920, "fps": 30}},
    ]
    for extra in _GROUP_EXTRA_SKILLS.get(group_type, []):
        seq.append({"skill_id": extra, "params": {}})
    seq += [
        {"skill_id": "subtitle_brand_style_v1", "params": {}},
        {"skill_id": "safe_concat_v1", "params": {"reencode": True, "target_seconds": TARGET_SECONDS}},
        {"skill_id": "probe_video_v1", "params": {}},
        {"skill_id": "playback_validate_v1", "params": {}},
        {"skill_id": "md5_duplicate_check_v1", "params": {}},
    ]
    return seq


def _output_requirements(ratio: str) -> dict:
    return {"ratio": ratio or "9:16", "fps": 30, "reencode": True,
            "target_seconds": TARGET_SECONDS, "cost": 0}


def _qa_expected() -> dict:
    return {"pts_monotonic": True, "playable_to_end": True,
            "duration_in_range": TARGET_SECONDS, "md5_unique": True}


def build_fission_plan(db: Session, tenant_id: str, order: ProductionOrder,
                       shots: list[dict], preview: bool = True) -> dict:
    """生成裂变计划（6 组 × 5 = 30 条 variant）。preview=True 不入库。"""
    ratio = order.ratio or "9:16"
    source_video_ids = []
    try:
        source_video_ids = json.loads(order.mother_video_ids) if order.mother_video_ids else []
    except (ValueError, TypeError):
        source_video_ids = []

    groups_meta, variants, used_skills = [], [], set()
    vcount = 0
    for group_type, center_idea, roles in GROUP_DEFS:
        groups_meta.append({"group_type": group_type, "center_idea": center_idea, "count": VARIANTS_PER_GROUP})
        for k in range(VARIANTS_PER_GROUP):
            vcount += 1
            seg = _segment_plan(shots, roles, k)
            seq = _skill_sequence(group_type)
            for step in seq:
                used_skills.add(step["skill_id"])
            vid = f"var_prev_{vcount:02d}" if preview else uuid.uuid4().hex
            variants.append({
                "variant_id": vid,
                "tenant_id": tenant_id,                  # ⚠️ 每条 variant 必填 tenant_id
                "group_type": group_type,
                "center_idea": center_idea,
                "segment_plan": seg,
                "skill_sequence": seq,
                "asset_sequence": [],
                "output_requirements": _output_requirements(ratio),
                "qa_expected": _qa_expected(),
                "qa_status": "pending",
                "sort_order": vcount,
            })

    # 白名单自检：skill_sequence 不得越出 12 条 canonical（防漂移）
    seq_errors = skill_executor.validate_skill_sequence(
        [{"skill_id": s} for s in used_skills]
    )
    if seq_errors:
        raise ValueError(f"fission_plan skill_sequence 越出白名单: {seq_errors}")

    return {
        "fission_plan_id": f"preview_fp_{uuid.uuid4().hex[:8]}" if preview else uuid.uuid4().hex,
        "production_order_id": order.production_order_id,
        "tenant_id": tenant_id,
        "source_video_ids": source_video_ids,
        "target_count": len(variants),
        "groups": groups_meta,
        "required_skills": sorted(used_skills),
        "qa_gates": ["duration_check", "pts_check", "playback_validate", "md5_duplicate_check"],
        "variants": variants,
        "status": "preview",
        "contract_version": "1.0",
    }
