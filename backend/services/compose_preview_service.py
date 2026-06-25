"""Compose 预览服务（V4 P0-B）。

/api/compose/preview 调用：生成导演稿 + 结构化提示词 + 图片角色 + 费用预估，
**不调用火山、不扣费**，结果落 director_plans，供正式 compose 复用。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

import cost_engine
from config import settings
from models import DirectorPlan
from services import director_prompt_engine as dpe
from utils import image_url_check


def build_preview(db: Session, tenant_id: str, user_phone: str | None, prompt: str,
                  image_file_ids: list[str] | None, style: str, ratio: str,
                  duration: int, resolution: str) -> dict:
    """生成并落库导演稿预览。图片不可访问 → 抛 ImageAccessError（路由转中文错误）。"""
    # Step4：图片角色（1→first_frame，2-9→reference_image）
    roles = dpe.assign_image_roles(image_file_ids)
    # 图片公网 HTTPS 校验（无图=纯文生，合法）
    roles_with_url = image_url_check.resolve_image_roles(db, tenant_id, image_file_ids, roles)

    # Step1-5：导演稿一体化
    plan = dpe.build_director_plan(prompt, roles_with_url, style, duration)

    # 费用预估（不扣费，仅写一条 estimate 流水）
    estimated = cost_engine.cost_ledger.estimate(
        db, tenant_id, "compose", duration, resolution,
        model=settings.volc_model, user_phone=user_phone,
    )

    warnings = []
    if not roles_with_url:
        warnings.append("未提供图片，将使用纯文生模式（产品外观一致性较弱，建议上传产品图）。")
    if len(plan["text_prompt"]) > settings.compose_seg_max_chars * max(1, len(plan["storyboard"])):
        warnings.append("导演稿较长，正式生成时将分段提交。")

    plan_id = uuid.uuid4().hex
    rec = DirectorPlan(
        id=plan_id, tenant_id=tenant_id, user_phone=user_phone, prompt=prompt,
        style=style, ratio=ratio, duration_seconds=duration, resolution=resolution,
        director_json=json.dumps(plan["storyboard"], ensure_ascii=False),
        seedance_text_prompt=plan["text_prompt"],
        image_roles_json=json.dumps(roles_with_url, ensure_ascii=False),
        director_prompt_version=plan["versions"]["director_prompt_version"],
        style_preset_version=plan["versions"]["style_preset_version"],
        negative_words_version=plan["versions"]["negative_words_version"],
        estimated_cost=estimated, status="preview",
    )
    db.add(rec)
    db.commit()

    return {
        "director_plan_id": plan_id,
        "director_plan": {
            "brand_context": plan["brand_context"],
            "storyboard": plan["storyboard"],
            "versions": plan["versions"],
        },
        "seedance_text_prompt": plan["text_prompt"],
        "seedance_content": plan["content"],     # 含 image_url role，供前端展示/调试
        "image_roles": roles_with_url,
        "estimated_cost": estimated,
        "ratio": ratio,
        "resolution": resolution,
        "duration": duration,
        "generate_audio": settings.compose_generate_audio,
        "warnings": warnings,
    }


def get_plan(db: Session, tenant_id: str, plan_id: str) -> DirectorPlan | None:
    return (
        db.query(DirectorPlan)
        .filter(DirectorPlan.id == plan_id, DirectorPlan.tenant_id == tenant_id)
        .first()
    )
