"""编排流水线服务（V4 P2B-A · orchestration_pipeline_v1）。

把 1 个生产单编成 30 条不同的 VariantPlan + ExecutionPlan（6 组 × 5 条），deterministic、
零成本、零执行：每条调用 6 个 L2 技能只产出 plan（不调 L1/remixer/ffmpeg/火山/LLM）。

输出供 execution_plan_service preview/confirm 使用。
"""

from __future__ import annotations

from services import p2b_l2_skills as l2
from services.p2b_skill_catalog import (
    GROUP_ROLE_SEQUENCE, GROUP_TYPE_CN, GROUP_TYPE_DESC, GROUP_TYPE_ORDER,
    HIGHLIGHT_FOCUS_CN, HIGHLIGHT_FOCUS_ORDER, PLATFORM_CN, ROLE_CN,
    VISUAL_STYLE_CN, VISUAL_STYLE_ORDER, chain_entry,
)

VARIANTS_PER_GROUP = 5

# 每条 variant 的 L2/L1 技能链（canonical skill_id；§3.7 默认链）
_SKILL_CHAIN_IDS = [
    "rhythm_edit_v1", "smooth_transition_v1", "narrative_subtitle_v1",
    "highlight_card_v1", "safe_concat_v1", "playback_validate_v1", "active_dedup_v1",
]

_SUBTITLE_SPEED = {"cinematic": "slow", "elegant": "slow", "minimal": "standard",
                   "trendy": "fast", "energetic": "fast"}


def _pick_shots(shots: list[dict], roles: list[str], variant_index: int) -> list[dict]:
    """按 group 的 role 序列选镜头；同 role 多条按 variant_index 轮转；缺失则全局兜底。"""
    picked = []
    for j, role in enumerate(roles):
        same = [s for s in shots if s.get("role") == role]
        pool = same or shots
        if not pool:
            continue
        picked.append(pool[(variant_index + j) % len(pool)])
    return picked or shots[:1]


def _cta_plan(highlight_focus: str, theme: dict) -> dict:
    return {
        "position": "结尾",
        "text": theme.get("cta_intent", "私信领取试用装"),
        "style": "行动号召大字",
        "reason": f"结合「{HIGHLIGHT_FOCUS_CN.get(highlight_focus, highlight_focus)}」文案重点，"
                  f"结尾给出明确行动号召，降低用户决策成本",
    }


def _qa_expected(lo: float, hi: float) -> list[dict]:
    return [
        {"item": "时长", "standard": f"{int(lo)}-{int(hi)}秒", "reason": "符合短视频完播率最优区间"},
        {"item": "PTS单调", "standard": "时间戳单调递增", "reason": "保证不卡顿、不冻结"},
        {"item": "可播放到结尾", "standard": "完整解码", "reason": "避免 14 秒卡死类问题"},
        {"item": "参数指纹唯一", "standard": "30条互不相同", "reason": "源头主动去重"},
        {"item": "中心思想对齐", "standard": "theme_kernel_id 一致", "reason": "裂变不跑题"},
    ]


def build_variant(shots: list[dict], theme: dict, group_type: str, group_index: int,
                  variant_no: int, lo: float, hi: float) -> dict:
    """生成单条 VariantPlan（含 6 个工艺计划 + craft_explanation）。"""
    focus = HIGHLIGHT_FOCUS_ORDER[(group_index - 1) % 5]
    style = VISUAL_STYLE_ORDER[(group_index - 1) % 5]
    roles = GROUP_ROLE_SEQUENCE.get(group_type, ["pain", "product", "brand"])
    sel = _pick_shots(shots, roles, group_index - 1)

    brief = theme.get("source_brief", {})
    brand = brief.get("brand_name", "本品牌")
    pain_words = brief.get("pain_points", ["皱纹"])
    must_keep = theme.get("must_keep_points", [])

    rhythm = l2.rhythm_edit_plan(sel, (lo, hi), style, group_index)
    transition = l2.smooth_transition_plan(sel, style)
    subtitle = l2.narrative_subtitle_plan(sel, rhythm, brand, must_keep)
    highlight = l2.highlight_card_plan(group_type, pain_words, brand)
    card_style = highlight["cards"][0]["style"] if highlight["cards"] else ""
    trans_type = transition["transitions"][0]["type"] if transition["transitions"] else "无"
    uniqueness = l2.uniqueness_plan(group_type, group_index, focus, style, sel, card_style, trans_type)

    narrative = [ROLE_CN.get(s["role"], s["role"]) for s in sel]
    asset_plan = [{"asset_id": str(s.get("source_video_id") or s.get("shot_id")),
                   "role": ROLE_CN.get(s["role"], s["role"]),
                   "segment": {"in": s.get("start_time"), "out": s.get("end_time")},
                   "reason": f"{ROLE_CN.get(s['role'], s['role'])}镜头承接本条叙事"} for s in sel]

    g_cn = GROUP_TYPE_CN.get(group_type, group_type)
    craft = (
        f"【第{(variant_no - 1) // 5 + 1}组第{group_index}条·{g_cn}·{VISUAL_STYLE_CN.get(style, style)}】\n"
        f"叙事结构：{g_cn}（{GROUP_TYPE_DESC.get(group_type, '')}），镜头顺序 {'→'.join(narrative)}。\n"
        f"节奏：{rhythm['explanation']}\n"
        f"转场：{transition['explanation']}\n"
        f"字幕：{subtitle['explanation']}\n"
        f"高光卡：{highlight['explanation']}\n"
        f"差异化：{uniqueness['explanation']}"
    )

    return {
        "variant_id": f"var_{variant_no:02d}",
        "production_order_id": theme["production_order_id"],
        "fission_plan_id": None,
        "group_type": group_type,
        "group_type_cn": g_cn,
        "group_index": group_index,
        "theme_kernel_id": theme["theme_kernel_id"],
        "theme_alignment_score": 1.0,
        "highlight_focus": focus,
        "highlight_focus_cn": HIGHLIGHT_FOCUS_CN.get(focus, focus),
        "visual_style": style,
        "visual_style_cn": VISUAL_STYLE_CN.get(style, style),
        "asset_plan": asset_plan,
        "narrative_structure": narrative,
        "rhythm_plan": rhythm,
        "transition_plan": transition,
        "subtitle_plan": subtitle,
        "highlight_card_plan": highlight,
        "uniqueness_plan": uniqueness,
        "cta_plan": _cta_plan(focus, theme),
        "qa_expected": _qa_expected(lo, hi),
        "status": "preview",
        "craft_explanation": craft,
    }


def _skill_params(visual_style: str, lo: float, hi: float) -> dict:
    return {
        "rhythm_edit_v1": {"rhythm_profile": "default"},
        "smooth_transition_v1": {"transition_rules": "default"},
        "narrative_subtitle_v1": {"subtitle_speed": _SUBTITLE_SPEED.get(visual_style, "standard")},
        "highlight_card_v1": {"card_style": "bold"},
        "safe_concat_v1": {"reencode": True, "target_seconds": [lo, hi]},
        "playback_validate_v1": {},
        "active_dedup_v1": {"dedup_level": "full"},
    }


def build_execution_plan(variant: dict, theme: dict, lo: float, hi: float) -> dict:
    """从 VariantPlan 组装 ExecutionPlan（含 skill_chain canonical + craft_explanation）。"""
    po_id = theme["production_order_id"]
    return {
        "execution_plan_id": f"ep_{po_id}_{variant['variant_id'].split('_')[1]}",
        "production_order_id": po_id,
        "fission_plan_id": variant.get("fission_plan_id"),
        "variant_id": variant["variant_id"],
        "group_type": variant["group_type"],
        "group_type_cn": variant["group_type_cn"],
        "highlight_focus": variant["highlight_focus"],
        "highlight_focus_cn": variant["highlight_focus_cn"],
        "visual_style": variant["visual_style"],
        "visual_style_cn": variant["visual_style_cn"],
        "skill_chain": [chain_entry(sid) for sid in _SKILL_CHAIN_IDS],
        "skill_params": _skill_params(variant["visual_style"], lo, hi),
        "variant_plan": variant,
        "theme_kernel": theme,
        "status": "preview",
        "cost_estimate": 0.0,
        "execute_allowed": False,
        "craft_explanation": variant["craft_explanation"],
    }


def build_asset_manifest(order: dict) -> dict:
    """从 shot_maps 的 source_video_id + role 生成素材清单骨架（不做 AI 识别）。"""
    shots = order.get("shot_maps", [])
    assets, by_role = [], {"pain": [], "product": [], "result": [], "brand": [], "cta": []}
    for i, s in enumerate(shots, 1):
        aid = f"asset_{i:02d}"
        role = s.get("role", "product")
        assets.append({
            "asset_id": aid, "asset_type": "视频", "role": ROLE_CN.get(role, role),
            "quality_score": 0.8, "duration": (s.get("end_time") or 0) - (s.get("start_time") or 0),
            "orientation": order.get("ratio", "9:16"), "source": "user_upload",
            "source_video_id": s.get("source_video_id"), "shot_id": s.get("shot_id"),
        })
        if role in by_role:
            by_role[role].append(aid)
    return {
        "manifest_id": f"am_{order['production_order_id']}",
        "production_order_id": order["production_order_id"],
        "assets": assets,
        "pain_assets": by_role["pain"], "product_assets": by_role["product"],
        "result_assets": by_role["result"], "brand_assets": by_role["brand"],
        "cta_assets": by_role["cta"],
    }


def build_mother_video_plan(order: dict, theme: dict) -> dict:
    """从 shot_maps 映射 ShotBlock 骨架（L3 提示词块预留，P2B-A 不填）。"""
    storyboard = []
    for s in order.get("shot_maps", []):
        storyboard.append({
            "shot_index": s.get("sort_order", 0), "role": ROLE_CN.get(s.get("role"), s.get("role")),
            "text_content": s.get("text_content", ""), "visual_description": s.get("visual_description", ""),
            "suggested_duration": (s.get("end_time") or 0) - (s.get("start_time") or 0),
            "camera_hint": "", "lighting_hint": "", "motion_hint": "", "color_tone_hint": "",
        })
    return {
        "plan_id": f"mvp_{order['production_order_id']}",
        "theme_kernel_id": theme["theme_kernel_id"],
        "storyboard": storyboard, "prompt_blocks": [],
        "model_provider_reserved": "volcano_2_0",
        "output_ratio": order.get("ratio", "9:16"), "duration": order.get("duration", 15),
        "qa_gates": ["时长检查", "画幅检查", "钩子检查", "品牌露出检查", "字幕可读性检查"],
        "status": "preview", "l3_ready": False,
    }


def build_fission_intent(order: dict, theme: dict) -> dict:
    platform = order.get("platform", "douyin")
    return {
        "intent_id": f"fi_{order['production_order_id']}",
        "production_order_id": order["production_order_id"],
        "theme_kernel_id": theme["theme_kernel_id"],
        "target_count": 30, "platform": platform, "platform_cn": PLATFORM_CN.get(platform, platform),
        "fission_goal": theme.get("source_brief", {}).get("goal", "留资"),
        "variation_strategy": "叙事结构差异化",
        "keep_theme_locked": True,
        "allowed_variations": ["叙事结构", "镜头顺序", "文案重点", "字幕风格", "高光卡位置", "转场风格", "CTA表达"],
        "forbidden_variations": ["核心承诺", "品牌名", "产品功能", "必须保留的信息"],
        "group_types": [GROUP_TYPE_CN[g] for g in GROUP_TYPE_ORDER],
        "highlight_focuses": [HIGHLIGHT_FOCUS_CN[f] for f in HIGHLIGHT_FOCUS_ORDER],
        "visual_styles": [VISUAL_STYLE_CN[v] for v in VISUAL_STYLE_ORDER],
    }


def build_all(order: dict, theme: dict, lo: float, hi: float) -> dict:
    """生成 30 条 variant + 30 条 execution plan + 去重报告（deterministic）。"""
    shots = order.get("shot_maps", [])
    variants, plans = [], []
    n = 0
    for group_type in GROUP_TYPE_ORDER:
        for k in range(1, VARIANTS_PER_GROUP + 1):
            n += 1
            v = build_variant(shots, theme, group_type, k, n, lo, hi)
            variants.append(v)
            plans.append(build_execution_plan(v, theme, lo, hi))
    dedup = validate_uniqueness(variants)
    return {
        "asset_manifest": build_asset_manifest(order),
        "mother_video_plan": build_mother_video_plan(order, theme),
        "fission_intent": build_fission_intent(order, theme),
        "variants": variants,
        "execution_plans": plans,
        "dedup_report": dedup,
    }


def validate_uniqueness(variants: list[dict]) -> dict:
    """参数唯一性校验（§5.3）：30 条参数指纹必须完全不同。"""
    fingerprints = [v["uniqueness_plan"]["param_fingerprint"] for v in variants]
    unique = len(set(fingerprints))
    total = len(variants)
    details = [{
        "variant_id": v["variant_id"], "group_type": v["group_type_cn"],
        "highlight_focus": v["highlight_focus_cn"], "visual_style": v["visual_style_cn"],
        "differentiation_summary": "；".join(v["uniqueness_plan"]["differentiation_dimensions"][:4]),
    } for v in variants]
    return {
        "report_id": "dr_active", "total_variants": total, "unique_count": unique,
        "duplicate_count": total - unique, "dedup_rate": round(unique / total, 4) if total else 0.0,
        "dedup_strategy": "active_orchestration", "details": details,
        "note": "30条通过6种叙事结构×5种文案重点×5种视觉风格主动去重，参数组合完全不同。"
                "P2B-A不做画面检测，MD5兜底留待P2B-C。",
    }
