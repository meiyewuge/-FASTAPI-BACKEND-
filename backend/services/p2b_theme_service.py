"""中心思想服务（V4 P2B-A）。

从 P2A production_order + shot_maps（+ director_plan 品牌上下文）deterministic 生成：
- CreativeBrief 创作简报
- ThemeKernel 中心思想内核（裂变不跑题的核心锚点）

纯规则、零 LLM、零成本、不触发火山。
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models import DirectorPlan
from services.p2b_l2_skills import _PAIN_WORDS, _SELLING_WORDS
from services.p2b_skill_catalog import PLATFORM_CN, SCENARIO_CN

_GOAL_CTA = {
    "留资": "私信领取试用装", "涨粉": "点击关注，每天分享护肤干货",
    "私域": "添加微信领取专属方案", "复购": "下单立享老客回购价", "品牌背书": "了解更多品牌故事",
}


def _collect_words(shot_texts: list[str], lib: list[str]) -> list[str]:
    found = []
    for t in shot_texts:
        for w in lib:
            if w in (t or "") and w not in found:
                found.append(w)
    return found


def _brand_from_director(db: Session, tenant_id: str, director_plan_id: str | None) -> dict:
    """从 director_plan 取品牌/产品/卖点上下文（无则空）。"""
    if not director_plan_id:
        return {}
    plan = (
        db.query(DirectorPlan)
        .filter(DirectorPlan.id == director_plan_id, DirectorPlan.tenant_id == tenant_id)
        .first()
    )
    if plan is None:
        return {}
    ctx = {"prompt": plan.prompt or ""}
    try:
        sb = json.loads(plan.director_json) if plan.director_json else []
        # storyboard 无 brand_context；从 prompt 提取兜底
    except (ValueError, TypeError):
        sb = []
    return ctx


def build_creative_brief(order: dict, shot_texts: list[str], brand_ctx: dict) -> dict:
    """从生产单 + 镜头文案推断创作简报。"""
    pains = _collect_words(shot_texts, _PAIN_WORDS) or ["皱纹", "暗沉"]
    sells = _collect_words(shot_texts, _SELLING_WORDS) or ["修复", "焕亮"]
    prompt = brand_ctx.get("prompt", "")
    brand = prompt.split("，")[0].split(",")[0][:12] if prompt else "本品牌"
    scenario = order.get("scenario") or "product_seeding"
    platform = order.get("platform") or "douyin"
    return {
        "brand_name": brand,
        "product_name": "核心产品",
        "target_audience": "30岁+女性，有" + "、".join(pains[:2]) + "困扰",
        "pain_points": pains[:3],
        "selling_points": sells[:3],
        "proof_points": ["真实用户口碑", "成分可查"],
        "tone": "专业",
        "platform": platform,
        "goal": "留资",
        "user_requirement": prompt,
        "video_assets": [str(order.get("director_plan_id") or "")],
        "image_assets": [],
        "text_assets": [],
        "scenario_cn": SCENARIO_CN.get(scenario, scenario),
        "platform_cn": PLATFORM_CN.get(platform, platform),
    }


def build_theme_kernel(db: Session, tenant_id: str, order: dict) -> dict:
    """生成 ThemeKernel（deterministic）。order 来自 production_order_service.get。"""
    po_id = order["production_order_id"]
    shots = order.get("shot_maps", [])
    shot_texts = [s.get("text_content", "") for s in shots]
    brand_ctx = _brand_from_director(db, tenant_id, order.get("director_plan_id"))
    brief = build_creative_brief(order, shot_texts, brand_ctx)

    brand = brief["brand_name"]
    pains = brief["pain_points"]
    sells = brief["selling_points"]
    goal = brief["goal"]
    pain_cn = "、".join(pains[:2])
    sell_cn = "、".join(sells[:2])

    core_message = f"30岁+{pain_cn}不可怕，{brand}帮你{sell_cn}"
    return {
        "theme_kernel_id": f"tk_{po_id}",
        "production_order_id": po_id,
        "core_message": core_message,
        "emotional_hook": f"看到镜子里{pain_cn}的自己，真的会焦虑",
        "main_promise": f"{sell_cn}，让肌肤回到更好的状态",
        "cta_intent": _GOAL_CTA.get(goal, "私信领取试用装"),
        "must_keep_points": [brand] + sells[:2] + ["核心承诺"],
        "must_not_change": ["不能虚假宣传", "不能改变产品功能", "品牌名", "必须保留的信息"],
        "brand_memory_point": f"{brand}=专业{sells[0] if sells else '修复'}",
        "source_brief": brief,
        "locked": False,
    }
