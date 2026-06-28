"""P2B-B1 小批量真实执行服务（V4 P2B-B1）。

读取 P2B-A confirmed execution_plans → 绑定真实 source_video_id → 复用 plan_executor 真实成片
→ 写 videos(type=viral, batch_id=run_id) + p2b_execution_run_items；run 维度记录 p2b_execution_runs。

source_video_id 硬校验（preview 阶段即失败）：属本租户 / 记录存在 / type=mother / 非缺陷源 /
本地文件存在 / ffprobe 可读 / duration 足够支撑 [lo,hi]。
真实执行 cost=0、不触发火山、不调 LLM、不写 P2A/P2B-A 表。
"""

from __future__ import annotations

import json
import os
import uuid

from sqlalchemy.orm import Session

import cost_engine
from b_engine import plan_executor, qa_checks
from config import settings
from models import ExecutionPlan, P2bExecutionRun, P2bExecutionRunItem, Video
from utils import video_storage

# 首批建议覆盖的 group_type（pain_first / selling_first / result_close）
FIRST_BATCH_GROUPS = ["pain_first", "selling_first", "result_close"]


def _targets() -> tuple[float, float, float]:
    return settings.b_remix_target_lo, settings.b_remix_target_hi, settings.b_remix_duration_tol


def validate_source(db: Session, tenant_id: str, source_video_id: int) -> dict:
    """源视频硬校验。返回 {ok, reason, path, duration, audio}。"""
    if source_video_id in (settings.p2b_b1_defect_source_ids or []):
        return {"ok": False, "reason": f"source_video_id={source_video_id} 为已知缺陷源，禁用"}
    v = (
        db.query(Video)
        .filter(Video.id == source_video_id, Video.tenant_id == tenant_id)
        .first()
    )
    if v is None:
        return {"ok": False, "reason": "源视频不存在或不属于当前租户"}
    if v.type != "mother":
        return {"ok": False, "reason": f"源视频 type={v.type}，需为 mother"}
    path = video_storage.local_path(v.id, "mother")
    if not os.path.exists(path):
        return {"ok": False, "reason": f"源视频本地文件缺失：{path}"}
    dur = qa_checks.probe_duration(path)
    if not dur or dur <= 0:
        return {"ok": False, "reason": "源视频 ffprobe 不可读"}
    lo, hi, _ = _targets()
    if dur < lo + 1.0:
        return {"ok": False, "reason": f"源视频时长 {dur:.1f}s 不足以支撑 [{lo:.0f},{hi:.0f}] 输出"}
    return {"ok": True, "reason": "", "path": path, "duration": dur,
            "audio": qa_checks.has_audio(path)}


def eligible_plans(db: Session, tenant_id: str, production_order_id: str) -> list[dict]:
    """该生产单下 confirmed 的执行计划 + execute_ready。"""
    rows = (
        db.query(ExecutionPlan)
        .filter(ExecutionPlan.tenant_id == tenant_id,
                ExecutionPlan.production_order_id == production_order_id,
                ExecutionPlan.status == "confirmed")
        .order_by(ExecutionPlan.variant_id.asc())
        .all()
    )
    out = []
    for e in rows:
        vp = plan_executor._as_obj(e.variant_plan_json)
        tk = plan_executor._as_obj(e.theme_kernel_json)
        ready = bool(vp.get("rhythm_plan") and vp.get("transition_plan"))
        out.append({
            "execution_plan_id": e.execution_plan_id, "variant_id": e.variant_id,
            "group_type": e.group_type, "highlight_focus": e.highlight_focus,
            "visual_style": e.visual_style, "theme_core_message": tk.get("core_message", ""),
            "execute_ready": ready,
            "execute_ready_reason": "" if ready else "variant_plan 缺 rhythm/transition",
        })
    return out


def _select_plans(db: Session, tenant_id: str, production_order_id: str,
                  plan_ids: list[str], max_items: int) -> list[ExecutionPlan]:
    rows = (
        db.query(ExecutionPlan)
        .filter(ExecutionPlan.tenant_id == tenant_id,
                ExecutionPlan.production_order_id == production_order_id,
                ExecutionPlan.status == "confirmed",
                ExecutionPlan.execution_plan_id.in_(plan_ids))
        .all()
    )
    by_id = {r.execution_plan_id: r for r in rows}
    ordered = [by_id[i] for i in plan_ids if i in by_id]      # 保持请求顺序
    return ordered[:max_items]


def preview_run(db: Session, tenant_id: str, production_order_id: str,
                plan_ids: list[str], source_video_id: int, max_items: int) -> dict:
    """预览本次将执行哪几条（不入库、不生成）。"""
    src = validate_source(db, tenant_id, source_video_id)
    if not src["ok"]:
        return {"ok": False, "code": 2002, "reason": src["reason"]}
    selected = _select_plans(db, tenant_id, production_order_id, plan_ids, max_items)
    if not selected:
        return {"ok": False, "code": 3001, "reason": "未找到可执行的 confirmed execution_plan"}
    lo, hi, _ = _targets()
    items = []
    for e in selected:
        vp = plan_executor._as_obj(e.variant_plan_json)
        plan = plan_executor.derive_windows(vp, src["duration"], lo, hi,
                                            seed=plan_executor._seed_of(e.variant_id))
        items.append({
            "execution_plan_id": e.execution_plan_id, "variant_id": e.variant_id,
            "group_type": e.group_type,
            "segments": len(plan["windows"]),
            "target_output": plan["target_output"],
            "sum_transition": plan["sum_transition"],
            "transitions": [{"type_cn": t["type_cn"], "exec": t["exec"], "duration": t["duration"]}
                            for t in plan["transitions"]],
        })
    # P2B-B2：附带可见层字体健康（additive，不改既有字段语义）
    fh = plan_executor.font_health()
    return {"ok": True, "data": {
        "production_order_id": production_order_id, "source_video_id": source_video_id,
        "source_duration": round(src["duration"], 2), "selected": items,
        "expected_outputs": len(items), "expected_cost": 0,
        "execution_mode": "staging_only",
        "visible_layer_ready": fh["visible_layer_ready"],
        "visible_layer": fh,
    }}


def execute_run(db: Session, tenant_id: str, user_phone: str | None, production_order_id: str,
                plan_ids: list[str], source_video_id: int, max_items: int, app_env: str) -> dict:
    """真实执行（同步，小批量）。写 run/items/videos。cost=0。"""
    src = validate_source(db, tenant_id, source_video_id)
    if not src["ok"]:
        return {"ok": False, "code": 2002, "reason": src["reason"]}
    selected = _select_plans(db, tenant_id, production_order_id, plan_ids, max_items)
    if not selected:
        return {"ok": False, "code": 3001, "reason": "未找到可执行的 confirmed execution_plan"}

    lo, hi, tol = _targets()
    W, H, FPS = settings.b_remix_width, settings.b_remix_height, settings.b_remix_fps
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    run = P2bExecutionRun(
        run_id=run_id, tenant_id=tenant_id, production_order_id=production_order_id,
        fission_plan_id=selected[0].fission_plan_id, source_video_id=source_video_id,
        run_name=f"P2B-B1 {production_order_id}", run_type="p2b_b1_small_batch",
        status="running", max_items=max_items, requested_count=len(selected),
        cost_estimate=0.0, execute_allowed=1, app_env=app_env,
    )
    db.add(run); db.commit()

    viral_dir = os.path.join(settings.storage_dir, "viral")
    os.makedirs(viral_dir, exist_ok=True)
    import tempfile
    work = tempfile.mkdtemp()
    batch_md5: set[str] = set()
    completed = failed = 0
    item_results = []

    for e in selected:
        item = P2bExecutionRunItem(
            item_id=f"it_{uuid.uuid4().hex[:12]}", run_id=run_id, tenant_id=tenant_id,
            execution_plan_id=e.execution_plan_id, variant_id=e.variant_id,
            group_type=e.group_type, status="running",
        )
        db.add(item); db.commit()
        tmp_out = os.path.join(work, f"{e.execution_plan_id}.mp4")
        try:
            res = plan_executor.execute_plan(
                src["path"], src["duration"], src["audio"], tmp_out, e.variant_plan_json,
                W, H, FPS, lo, hi, tol, batch_md5, variant_id=e.variant_id,
            )
        except Exception as ex:  # noqa: BLE001  执行器异常不拖死整批
            item.status = "failed"; item.error_message = f"executor error: {ex}"[:480]
            db.commit(); failed += 1
            item_results.append({"execution_plan_id": e.execution_plan_id, "status": "failed"})
            continue

        qa = res["qa"]
        if not res["ok"]:
            item.status = "failed"
            item.error_message = f"QA failed: {qa.get('final_status')}"
            item.qa_json = json.dumps(qa, ensure_ascii=False)
            db.commit(); failed += 1
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            item_results.append({"execution_plan_id": e.execution_plan_id, "status": "failed"})
            continue

        # QA 通过 → 写 videos(viral) + 归档文件
        v = Video(
            tenant_id=tenant_id, type="viral", source_type="remixed", storage_status="active",
            title=plan_executor._as_obj(e.theme_kernel_json).get("core_message", "")[:120] or e.variant_id,
            strategy=e.group_type, source_video_id=source_video_id, parent_video_id=source_video_id,
            batch_id=run_id, duration_seconds=qa_checks.probe_duration(tmp_out),
            meta=json.dumps({"p2b_b1": True, "execution_plan_id": e.execution_plan_id,
                             "applied": res["applied"], "fallbacks": res["fallbacks"]},
                            ensure_ascii=False),
        )
        db.add(v); db.flush()
        final_path = os.path.join(viral_dir, f"{v.id}.mp4")
        os.replace(tmp_out, final_path)
        # P2B-B2: copy SRT sidecar if exists
        tmp_srt = os.path.splitext(tmp_out)[0] + ".srt"
        if os.path.exists(tmp_srt):
            import shutil
            shutil.copy2(tmp_srt, os.path.splitext(final_path)[0] + ".srt")
        v.local_url = video_storage.local_url(v.id, "viral")
        v.download_url = v.local_url; v.share_url = v.local_url
        batch_md5.add(qa["md5"])

        # B 台本地裂变 = 0 元
        cost_engine.record(db, tenant_id, "video.p2b_b1", 0, run_id,
                           provider="local_ffmpeg", duration=v.duration_seconds, amount=0.0)

        item.status = "done"; item.video_id = v.id; item.output_path = final_path
        item.duration = v.duration_seconds; item.md5 = qa["md5"]
        # P2B-B2: merge fallbacks into qa for reporting
        qa.update(res.get("fallbacks", {}))
        item.qa_json = json.dumps(qa, ensure_ascii=False)
        item.rhythm_applied_json = json.dumps(res["plan"].get("windows"), ensure_ascii=False) \
            if isinstance(res.get("plan"), dict) else None
        item.transition_applied_json = json.dumps(res["plan"].get("transitions"), ensure_ascii=False) \
            if isinstance(res.get("plan"), dict) else None
        item.subtitle_applied_json = json.dumps(res["applied"].get("subtitles"), ensure_ascii=False)
        item.highlight_card_applied_json = json.dumps(res["applied"].get("highlight"), ensure_ascii=False)
        item.cta_applied_json = json.dumps(res["applied"].get("cta"), ensure_ascii=False)
        item.dedup_applied_json = json.dumps(
            {"md5": qa["md5"], "fingerprint": plan_executor._as_obj(e.variant_plan_json)
             .get("uniqueness_plan", {}).get("param_fingerprint")}, ensure_ascii=False)
        db.commit(); completed += 1
        item_results.append({"execution_plan_id": e.execution_plan_id, "status": "done",
                             "video_id": v.id, "duration": v.duration_seconds, "md5": qa["md5"]})

    run.completed = completed; run.failed = failed
    run.status = "done" if failed == 0 else ("partial_done" if completed > 0 else "failed")
    db.commit()

    return {"ok": True, "data": {
        "run_id": run_id, "status": run.status, "requested": len(selected),
        "completed": completed, "failed": failed, "cost": 0,
        "execute_allowed": True, "items": item_results,
    }}


def get_run(db: Session, tenant_id: str, run_id: str) -> dict | None:
    r = (db.query(P2bExecutionRun)
         .filter(P2bExecutionRun.run_id == run_id, P2bExecutionRun.tenant_id == tenant_id).first())
    if r is None:
        return None
    return {
        "run_id": r.run_id, "tenant_id": r.tenant_id, "production_order_id": r.production_order_id,
        "source_video_id": r.source_video_id, "status": r.status, "run_type": r.run_type,
        "max_items": r.max_items, "requested_count": r.requested_count,
        "completed": r.completed, "failed": r.failed, "cost_estimate": r.cost_estimate,
        "execute_allowed": bool(r.execute_allowed), "app_env": r.app_env,
    }


def list_items(db: Session, tenant_id: str, run_id: str) -> dict:
    rows = (db.query(P2bExecutionRunItem)
            .filter(P2bExecutionRunItem.run_id == run_id,
                    P2bExecutionRunItem.tenant_id == tenant_id)
            .order_by(P2bExecutionRunItem.id.asc()).all())
    def _j(s):
        return json.loads(s) if s else None
    items = [{
        "item_id": it.item_id, "execution_plan_id": it.execution_plan_id, "variant_id": it.variant_id,
        "group_type": it.group_type, "status": it.status, "video_id": it.video_id,
        "output_path": it.output_path, "error_message": it.error_message,
        "duration": it.duration, "md5": it.md5,
        "transition_applied": _j(it.transition_applied_json),
        "subtitle_applied": _j(it.subtitle_applied_json),
        "highlight_card_applied": _j(it.highlight_card_applied_json),
        "cta_applied": _j(it.cta_applied_json),
        "dedup_applied": _j(it.dedup_applied_json),
    } for it in rows]
    return {"run_id": run_id, "total": len(items), "items": items}
