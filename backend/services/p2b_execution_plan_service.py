"""执行计划服务（V4 P2B-A）。

preview：deterministic 生成 30 条 ExecutionPlan，**不入库**、cost=0、execute_allowed=false。
confirm：deterministic 重新生成 → 入库 execution_plans(status=confirmed) + skill_executions(status=planned)，
         同一 (tenant_id, production_order_id, plan_version) 幂等（DB 唯一索引 + 先查兜底）。
get / explain / by-production-order：均从持久化 JSON 返回（不依赖临时内存）。

不执行真实视频、不调 remixer/ffmpeg/火山/LLM、不写 videos、不改 P2A 表。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from models import ExecutionPlan, FissionPlan, SkillExecution
from services import p2b_orchestration_service as orch
from services import p2b_theme_service as theme_svc
from services import production_order_service


def _targets() -> tuple[float, float]:
    return settings.b_remix_target_lo, settings.b_remix_target_hi


def _validate_fission_plan(db: Session, tenant_id: str, production_order_id: str,
                           fission_plan_id: str | None) -> bool:
    """fission_plan_id 校验（V1.1 硬锁）。

    - None：可选，沿用 deterministic 生成逻辑 → 合法。
    - 非空：必须在 P2A FissionPlan 表存在，且归属同一 production_order_id + tenant_id。
      不存在/越权 → False（禁止把未校验的 fission_plan_id 写入 execution_plans）。
    """
    if not fission_plan_id:
        return True
    fp = (
        db.query(FissionPlan)
        .filter(
            FissionPlan.fission_plan_id == fission_plan_id,
            FissionPlan.production_order_id == production_order_id,
            FissionPlan.tenant_id == tenant_id,
        )
        .first()
    )
    return fp is not None


def _build(db: Session, tenant_id: str, production_order_id: str,
           fission_plan_id: str | None) -> dict | None:
    """公共构建：order → theme → 30 计划。order 不存在/越权、fission_plan_id 非法 → None。"""
    order = production_order_service.get(db, tenant_id, production_order_id)
    if order is None:
        return None
    # V1.1：非空 fission_plan_id 必须校验存在 + 归属（tenant + production_order）
    if not _validate_fission_plan(db, tenant_id, production_order_id, fission_plan_id):
        return None
    theme = theme_svc.build_theme_kernel(db, tenant_id, order)
    lo, hi = _targets()
    bundle = orch.build_all(order, theme, lo, hi)
    # fission_plan_id 可选：传入则回填到每条计划（P2A 不要求 fission_plan 入库）
    if fission_plan_id:
        for p in bundle["execution_plans"]:
            p["fission_plan_id"] = fission_plan_id
            p["variant_plan"]["fission_plan_id"] = fission_plan_id
    bundle["theme_kernel"] = theme
    bundle["order"] = order
    return bundle


def build_theme_only(db: Session, tenant_id: str, production_order_id: str) -> dict | None:
    order = production_order_service.get(db, tenant_id, production_order_id)
    if order is None:
        return None
    return theme_svc.build_theme_kernel(db, tenant_id, order)


def preview(db: Session, tenant_id: str, production_order_id: str,
            fission_plan_id: str | None) -> dict | None:
    """预览 30 条执行计划（不入库）。"""
    bundle = _build(db, tenant_id, production_order_id, fission_plan_id)
    if bundle is None:
        return None
    return {
        "total": len(bundle["execution_plans"]),
        "execution_plans": bundle["execution_plans"],
        "theme_kernel": bundle["theme_kernel"],
        "dedup_report": bundle["dedup_report"],
        "cost_estimate": 0,
        "execute_allowed": False,
    }


def _existing(db: Session, tenant_id: str, production_order_id: str, version: str) -> list[ExecutionPlan]:
    return (
        db.query(ExecutionPlan)
        .filter(ExecutionPlan.tenant_id == tenant_id,
                ExecutionPlan.production_order_id == production_order_id,
                ExecutionPlan.plan_version == version)
        .order_by(ExecutionPlan.variant_id.asc())
        .all()
    )


def confirm(db: Session, tenant_id: str, production_order_id: str,
            fission_plan_id: str | None, operator: str | None) -> dict | None:
    """确认入库（幂等）。order 不存在/越权 → None。"""
    version = settings.p2b_plan_version

    # 幂等：已存在直接返回（不重复生成）
    existing = _existing(db, tenant_id, production_order_id, version)
    if existing:
        return {
            "production_order_id": production_order_id,
            "total": len(existing),
            "execution_plan_ids": [e.execution_plan_id for e in existing],
            "status": "confirmed",
            "cost_estimate": 0,
            "execute_allowed": False,
            "idempotent": True,
        }

    bundle = _build(db, tenant_id, production_order_id, fission_plan_id)
    if bundle is None:
        return None

    theme = bundle["theme_kernel"]
    now = datetime.utcnow().isoformat()
    theme_json = json.dumps(theme, ensure_ascii=False)
    am_json = json.dumps(bundle["asset_manifest"], ensure_ascii=False)
    mvp_json = json.dumps(bundle["mother_video_plan"], ensure_ascii=False)
    fi_json = json.dumps(bundle["fission_intent"], ensure_ascii=False)
    brief_json = json.dumps(theme.get("source_brief", {}), ensure_ascii=False)

    plan_ids = []
    for p in bundle["execution_plans"]:
        v = p["variant_plan"]
        db.add(ExecutionPlan(
            execution_plan_id=p["execution_plan_id"],
            tenant_id=tenant_id,
            production_order_id=production_order_id,
            fission_plan_id=p.get("fission_plan_id"),
            variant_id=p["variant_id"],
            plan_version=version,
            group_type=p["group_type"],
            highlight_focus=p["highlight_focus"],
            visual_style=p["visual_style"],
            skill_chain=json.dumps(p["skill_chain"], ensure_ascii=False),
            skill_params=json.dumps(p["skill_params"], ensure_ascii=False),
            creative_brief_json=brief_json,
            theme_kernel_json=theme_json,
            asset_manifest_json=am_json,
            mother_video_plan_json=mvp_json,
            fission_intent_json=fi_json,
            variant_plan_json=json.dumps(v, ensure_ascii=False),
            rhythm_plan=json.dumps(v["rhythm_plan"], ensure_ascii=False),
            transition_plan=json.dumps(v["transition_plan"], ensure_ascii=False),
            subtitle_plan=json.dumps(v["subtitle_plan"], ensure_ascii=False),
            highlight_card_plan=json.dumps(v["highlight_card_plan"], ensure_ascii=False),
            uniqueness_plan=json.dumps(v["uniqueness_plan"], ensure_ascii=False),
            status="confirmed",
            confirmed_at=now,
            cost_estimate=0.0,
            execute_allowed=0,
            craft_explanation=p["craft_explanation"],
        ))
        # skill_executions：每条计划每个技能一条，status=planned（不执行）
        for step in p["skill_chain"]:
            sid = step["skill_id"]
            db.add(SkillExecution(
                execution_id=f"se_{p['execution_plan_id']}_{sid}",
                tenant_id=tenant_id,
                execution_plan_id=p["execution_plan_id"],
                variant_id=p["variant_id"],
                skill_id=sid,
                skill_layer="L2" if sid.endswith("_v1") and sid in (
                    "rhythm_edit_v1", "smooth_transition_v1", "narrative_subtitle_v1",
                    "highlight_card_v1", "active_dedup_v1", "orchestration_pipeline_v1") else "L1",
                input_payload=json.dumps(p["skill_params"].get(sid, {}), ensure_ascii=False),
                output_payload=None,
                status="planned",
            ))
        plan_ids.append(p["execution_plan_id"])

    try:
        db.commit()
    except IntegrityError:
        # 并发重复提交：回滚后返回已存在记录（幂等兜底）
        db.rollback()
        existing = _existing(db, tenant_id, production_order_id, version)
        return {
            "production_order_id": production_order_id,
            "total": len(existing),
            "execution_plan_ids": [e.execution_plan_id for e in existing],
            "status": "confirmed", "cost_estimate": 0, "execute_allowed": False,
            "idempotent": True,
        }

    return {
        "production_order_id": production_order_id,
        "total": len(plan_ids),
        "execution_plan_ids": plan_ids,
        "status": "confirmed",
        "cost_estimate": 0,
        "execute_allowed": False,
        "idempotent": False,
    }


def _row_to_full(e: ExecutionPlan) -> dict:
    def _j(s, d):
        return json.loads(s) if s else d
    return {
        "execution_plan_id": e.execution_plan_id,
        "production_order_id": e.production_order_id,
        "fission_plan_id": e.fission_plan_id,
        "variant_id": e.variant_id,
        "plan_version": e.plan_version,
        "group_type": e.group_type,
        "highlight_focus": e.highlight_focus,
        "visual_style": e.visual_style,
        "skill_chain": _j(e.skill_chain, []),
        "skill_params": _j(e.skill_params, {}),
        "creative_brief": _j(e.creative_brief_json, {}),
        "theme_kernel": _j(e.theme_kernel_json, {}),
        "asset_manifest": _j(e.asset_manifest_json, {}),
        "mother_video_plan": _j(e.mother_video_plan_json, {}),
        "fission_intent": _j(e.fission_intent_json, {}),
        "variant_plan": _j(e.variant_plan_json, {}),
        "status": e.status,
        "cost_estimate": e.cost_estimate,
        "execute_allowed": bool(e.execute_allowed),
        "craft_explanation": e.craft_explanation,
    }


def get(db: Session, tenant_id: str, execution_plan_id: str) -> dict | None:
    e = (
        db.query(ExecutionPlan)
        .filter(ExecutionPlan.execution_plan_id == execution_plan_id,
                ExecutionPlan.tenant_id == tenant_id)
        .first()
    )
    return _row_to_full(e) if e else None


def explain(db: Session, tenant_id: str, execution_plan_id: str) -> dict | None:
    """工艺说明：全部来自持久化 JSON（variant_plan_json / theme_kernel_json）。"""
    e = (
        db.query(ExecutionPlan)
        .filter(ExecutionPlan.execution_plan_id == execution_plan_id,
                ExecutionPlan.tenant_id == tenant_id)
        .first()
    )
    if e is None:
        return None
    v = json.loads(e.variant_plan_json) if e.variant_plan_json else {}
    tk = json.loads(e.theme_kernel_json) if e.theme_kernel_json else {}
    return {
        "execution_plan_id": e.execution_plan_id,
        "variant_id": e.variant_id,
        "theme_core_message": tk.get("core_message", ""),
        "craft_explanation": e.craft_explanation or v.get("craft_explanation", ""),
        "rhythm_explanation": v.get("rhythm_plan", {}).get("explanation", ""),
        "transition_explanation": v.get("transition_plan", {}).get("explanation", ""),
        "subtitle_explanation": v.get("subtitle_plan", {}).get("explanation", ""),
        "highlight_card_explanation": v.get("highlight_card_plan", {}).get("explanation", ""),
        "uniqueness_explanation": v.get("uniqueness_plan", {}).get("explanation", ""),
    }


def list_by_production_order(db: Session, tenant_id: str, production_order_id: str) -> dict:
    rows = (
        db.query(ExecutionPlan)
        .filter(ExecutionPlan.tenant_id == tenant_id,
                ExecutionPlan.production_order_id == production_order_id,
                ExecutionPlan.status == "confirmed")
        .order_by(ExecutionPlan.variant_id.asc())
        .all()
    )
    items = [{
        "execution_plan_id": e.execution_plan_id,
        "variant_id": e.variant_id,
        "group_type": e.group_type,
        "status": e.status,
        "variant_plan_json": e.variant_plan_json,
        "craft_explanation": e.craft_explanation,
    } for e in rows]
    return {"production_order_id": production_order_id, "total": len(items), "execution_plans": items}
