"""生产单服务（V4 P2A）。

director_plan → production_order + shot_maps：
- preview：组装 preview 对象（status=preview），**不入库**、0 成本、不触发火山。
- create ：校验 director_plan 归属当前 tenant → 落库 production_order + shot_maps（必填 tenant_id）。
- get    ：返回 production_order + shot_maps（tenant 隔离）。

不写 videos、不调 remixer、不触发火山。
"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy.orm import Session

from models import DirectorPlan, ProductionOrder, ShotMap

# 平台 → 画幅
_PLATFORM_RATIO = {
    "douyin": "9:16", "kuaishou": "9:16", "shipinhao": "9:16", "xiaohongshu": "9:16",
}

# 角色关键词（命中 → 高置信度）
_ROLE_KEYWORDS = {
    "pain": ("痛点", "问题", "困扰", "烦恼", "难题", "焦虑"),
    "product": ("产品", "瓶身", "标签", "外观", "展示", "质地", "包装"),
    "solution": ("解决", "方案", "使用", "涂抹", "步骤", "方法"),
    "result": ("效果", "对比", "改善", "前后", "提升", "蜕变"),
    "brand": ("品牌", "slogan", "定格", "logo", "标识"),
    "cta": ("关注", "购买", "下单", "点击", "行动", "私信", "评论"),
}

# 缺省 QA gates（复用 b_engine/qa_checks 的 4 道 hard gate）
DEFAULT_QA_GATES = ["duration_check", "pts_check", "playback_validate", "md5_duplicate_check"]


def _parse_timecode(tc: str | None, idx: int, seg: float = 5.0) -> tuple[float, float]:
    """'0-5秒' → (0.0, 5.0)。解析失败按 idx 顺推。"""
    if tc:
        nums = re.findall(r"\d+(?:\.\d+)?", tc)
        if len(nums) >= 2:
            return float(nums[0]), float(nums[1])
    start = (idx - 1) * seg
    return start, start + seg


def _infer_role(description: str, line: str, idx: int, total: int) -> tuple[str, float]:
    """按描述/台词关键词 + 镜位推断 role，返回 (role, confidence)。"""
    text = f"{description or ''} {line or ''}"
    for role, kws in _ROLE_KEYWORDS.items():
        if any(k in text for k in kws):
            return role, 0.88
    # 关键词未命中 → 镜位兜底：首镜痛点、末镜 CTA、中间轮转
    if idx == 1:
        return "pain", 0.6
    if idx == total:
        return "cta", 0.6
    cycle = ["product", "solution", "result", "brand"]
    return cycle[(idx - 2) % len(cycle)], 0.55


def _ratio_for(platform: str | None) -> str:
    return _PLATFORM_RATIO.get((platform or "").lower(), "9:16")


def _fission_goal(scenario: str | None, platform: str | None) -> dict:
    return {
        "target_count": 30,
        "ratio_per_source": 10,
        "max_outputs": 50,
        "output_seconds": [25, 35],
    }


def _cost_policy() -> dict:
    return {"b_track_api_cost": 0, "allow_llm_assist": False, "compose_locked": True}


def _asset_policy() -> dict:
    return {
        "use_user_uploads": True,
        "use_brand_pack": False,
        "use_free_stock": False,
        "allow_paid_recommendation": False,
    }


def _build_shot_maps(plan: DirectorPlan, tenant_id: str, preview: bool) -> list[dict]:
    """从 director_plan.storyboard 抽取 shot_maps（preview 用临时 shot_id）。"""
    try:
        storyboard = json.loads(plan.director_json) if plan.director_json else []
    except (ValueError, TypeError):
        storyboard = []
    total = len(storyboard)
    shots: list[dict] = []
    for i, item in enumerate(storyboard, start=1):
        idx = int(item.get("index", i))
        start, end = _parse_timecode(item.get("timecode"), idx)
        role, conf = _infer_role(item.get("description", ""), item.get("line", ""), idx, total)
        sid = f"shot_prev_{idx:02d}" if preview else uuid.uuid4().hex
        shots.append({
            "shot_id": sid,
            "tenant_id": tenant_id,
            "source_video_id": None,
            "source_kind": "mother",
            "role": role,
            "start_time": start,
            "end_time": end,
            "text_content": item.get("line", ""),
            "visual_description": item.get("description", ""),
            "image_refs": [],
            "confidence": conf,
            "sort_order": idx,
        })
    return shots


def build_preview(db: Session, tenant_id: str, user_phone: str | None,
                  director_plan_id: str, scenario: str | None, platform: str | None) -> dict | None:
    """生产单 preview（不入库）。director_plan 不存在/不属于 tenant → None。"""
    plan = (
        db.query(DirectorPlan)
        .filter(DirectorPlan.id == director_plan_id, DirectorPlan.tenant_id == tenant_id)
        .first()
    )
    if plan is None:
        return None
    shots = _build_shot_maps(plan, tenant_id, preview=True)
    ratio = _ratio_for(platform) if platform else plan.ratio
    return {
        "production_order_id": f"preview_{uuid.uuid4().hex[:8]}",
        "director_plan_id": director_plan_id,
        "tenant_id": tenant_id,
        "scenario": scenario,
        "platform": platform,
        "ratio": ratio,
        "duration": plan.duration_seconds,
        "fission_goal": _fission_goal(scenario, platform),
        "qa_gates": list(DEFAULT_QA_GATES),
        "asset_policy": _asset_policy(),
        "shot_maps": shots,
        "status": "preview",
        "cost_policy": _cost_policy(),
        "contract_version": "1.0",
    }


def create(db: Session, tenant_id: str, user_phone: str | None,
           director_plan_id: str, scenario: str | None, platform: str | None,
           shot_maps_override: list[dict] | None = None) -> dict | None:
    """确认落库。director_plan 校验失败 → None。返回 {production_order_id, status}。"""
    plan = (
        db.query(DirectorPlan)
        .filter(DirectorPlan.id == director_plan_id, DirectorPlan.tenant_id == tenant_id)
        .first()
    )
    if plan is None:
        return None

    po_id = f"po_{uuid.uuid4().hex[:12]}"
    ratio = _ratio_for(platform) if platform else plan.ratio

    order = ProductionOrder(
        production_order_id=po_id,
        tenant_id=tenant_id,
        user_id=user_phone,
        scenario=scenario,
        platform=platform,
        ratio=ratio,
        duration=plan.duration_seconds,
        director_plan_id=director_plan_id,
        mother_video_ids=json.dumps([], ensure_ascii=False),
        asset_policy=json.dumps(_asset_policy(), ensure_ascii=False),
        selected_assets=json.dumps([], ensure_ascii=False),
        fission_goal=json.dumps(_fission_goal(scenario, platform), ensure_ascii=False),
        qa_gates=json.dumps(DEFAULT_QA_GATES, ensure_ascii=False),
        cost_policy=json.dumps(_cost_policy(), ensure_ascii=False),
        contract_version="1.0",
        status="confirmed",
    )
    db.add(order)

    # shot_maps：preview 抽取或前端覆盖；落库一律新 uuid shot_id 并强制 tenant_id
    raw_shots = shot_maps_override or _build_shot_maps(plan, tenant_id, preview=False)
    for i, sh in enumerate(raw_shots, start=1):
        db.add(ShotMap(
            shot_id=sh.get("shot_id") or uuid.uuid4().hex,
            production_order_id=po_id,
            tenant_id=tenant_id,                       # ⚠️ 强制填入 tenant_id
            source_video_id=sh.get("source_video_id"),
            source_kind=sh.get("source_kind", "mother"),
            role=sh.get("role", "product"),
            start_time=sh.get("start_time"),
            end_time=sh.get("end_time"),
            text_content=sh.get("text_content"),
            visual_description=sh.get("visual_description"),
            image_refs=json.dumps(sh.get("image_refs", []), ensure_ascii=False),
            confidence=sh.get("confidence", 0.0),
            sort_order=sh.get("sort_order", i),
            contract_version="1.0",
        ))
    db.commit()
    return {"production_order_id": po_id, "status": "confirmed"}


def _order_to_dict(order: ProductionOrder) -> dict:
    def _j(v, default):
        return json.loads(v) if v else default
    return {
        "production_order_id": order.production_order_id,
        "tenant_id": order.tenant_id,
        "user_id": order.user_id,
        "scenario": order.scenario,
        "platform": order.platform,
        "ratio": order.ratio,
        "duration": order.duration,
        "director_plan_id": order.director_plan_id,
        "mother_video_ids": _j(order.mother_video_ids, []),
        "asset_policy": _j(order.asset_policy, {}),
        "selected_assets": _j(order.selected_assets, []),
        "fission_goal": _j(order.fission_goal, {}),
        "qa_gates": _j(order.qa_gates, []),
        "cost_policy": _j(order.cost_policy, {}),
        "contract_version": order.contract_version,
        "status": order.status,
    }


def _shot_to_dict(sm: ShotMap) -> dict:
    return {
        "shot_id": sm.shot_id,
        "production_order_id": sm.production_order_id,
        "tenant_id": sm.tenant_id,
        "source_video_id": sm.source_video_id,
        "source_kind": sm.source_kind,
        "role": sm.role,
        "start_time": sm.start_time,
        "end_time": sm.end_time,
        "text_content": sm.text_content,
        "visual_description": sm.visual_description,
        "image_refs": json.loads(sm.image_refs) if sm.image_refs else [],
        "confidence": sm.confidence,
        "sort_order": sm.sort_order,
    }


def get(db: Session, tenant_id: str, production_order_id: str) -> dict | None:
    """生产单 + shot_maps（tenant 隔离）。不存在/越权 → None。"""
    order = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.production_order_id == production_order_id,
                ProductionOrder.tenant_id == tenant_id)
        .first()
    )
    if order is None:
        return None
    shots = (
        db.query(ShotMap)
        .filter(ShotMap.production_order_id == production_order_id,
                ShotMap.tenant_id == tenant_id)
        .order_by(ShotMap.sort_order.asc())
        .all()
    )
    data = _order_to_dict(order)
    data["shot_maps"] = [_shot_to_dict(s) for s in shots]
    return data
