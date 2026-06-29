"""V4 P2B-B3 三维差异评分闸门 · 服务层（只评分，不自动重剪/不生成/不扩批）。

读既有数据（零新增表）：videos.meta(audio_encoding/applied) + run_items.qa_json + *_applied_json +
audio_encoding_signature + visible_style_signature + windows metadata + 最终 mp4（仅抽帧）。
写：videos.meta.b3_score（每条）+ run_items.qa_json.b3_batch（整批），幂等覆盖（同 batch_id+b3_version 不追加）。
发布池契约：只读 batch_summary.pass=true 且 recommended_action=pass_to_publish_pool。
大 N 模拟：metadata-only，复用 plan_executor 确定性算法复算 signature/取窗，不渲染、不生成视频。
"""

from __future__ import annotations

import json
import os
import re
import subprocess

from sqlalchemy.orm import Session

from b_engine import b3_score, plan_executor
from config import settings
from models import ExecutionPlan, P2bExecutionRun, P2bExecutionRunItem, Video
from utils import video_storage


def _thr() -> dict:
    s = settings
    return {
        "vds_pass": s.p2b_b3_vds_pass, "visual_floor": s.p2b_b3_visual_floor,
        "text_floor": s.p2b_b3_text_floor, "kf_min_floor": s.p2b_b3_kf_min_floor,
        "visual_target": s.p2b_b3_visual_target, "text_target": s.p2b_b3_text_target,
        "audio_target": s.p2b_b3_audio_target, "keyframes": s.p2b_b3_keyframes,
        "audio_switch_low": s.p2b_b3_audio_switch_low, "audio_switch_high": s.p2b_b3_audio_switch_high,
        "calibration": s.p2b_b3_calibration, "b3_version": s.p2b_b3_version,
    }


def _as_obj(s):
    if not s:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _measure_mp4(path: str) -> dict:
    """质量维兜底实测（仅当 meta/qa 无实测时）：loudnorm analyze 读 I(LUFS)/TP(dBTP)，与 ECS 同口径。"""
    try:
        r = subprocess.run(["ffmpeg", "-i", path, "-map", "0:a", "-af",
                            "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
        m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
        if not m:
            return {}
        d = json.loads(m[-1])
        return {"lufs": float(d["input_i"]), "true_peak": float(d["input_tp"])}
    except Exception:  # noqa: BLE001
        return {}


def _gather_video(db: Session, item: P2bExecutionRunItem, with_frames: bool, k: int) -> dict:
    """从 run_item + videos.meta 汇集一条视频的评分输入（不改任何既有字段）。"""
    v = db.get(Video, item.video_id) if item.video_id else None
    meta = _as_obj(v.meta) if v and v.meta else {}
    qa = _as_obj(item.qa_json) or {}
    ae = (meta or {}).get("audio_encoding") or {}
    applied = (meta or {}).get("applied") or {}

    windows = _as_obj(item.rhythm_applied_json) or []
    transitions = _as_obj(item.transition_applied_json) or []
    subtitle_applied = _as_obj(item.subtitle_applied_json)
    highlight_applied = _as_obj(item.highlight_card_applied_json)
    cta_applied = _as_obj(item.cta_applied_json)

    # visible_style_signature + variation_dimensions：优先 applied，缺则按 variant 确定性复算（只读复算，不改 B2.1）
    vstyle_sig = applied.get("visible_style_signature")
    vdims = applied.get("variation_dimensions")
    if not vstyle_sig:
        vp = {}  # 仅复算可见层签名时不依赖 vp 细节
        try:
            style = plan_executor.resolve_visible_style(vp, item.variant_id)
            vstyle_sig = style["signature"]; vdims = style["variation_dimensions"]
        except Exception:  # noqa: BLE001
            vstyle_sig = "none"; vdims = {}

    # 质量实测优先级：meta.audio_encoding 实测 → meta.b3_measured → 缺失才重测 mp4（spec 允许）
    measured = (meta or {}).get("b3_measured") or {}
    has_meta_measure = any(ae.get(k2) is not None for k2 in ("measured_lufs", "measured_tp",
                                                             "integrated_lufs", "true_peak"))

    frame_hashes = None
    proxy_unavailable_reason = None
    path = video_storage.local_path(v.id, "viral") if v is not None else None
    if with_frames and v is not None:
        dur = item.duration or (v.duration_seconds if v else 0)
        if path and os.path.exists(path) and dur:
            frame_hashes = b3_score.frame_hashes(path, float(dur), k)
            if frame_hashes is None:
                proxy_unavailable_reason = "frame_extract_failed"
            if not measured and not has_meta_measure:
                measured = _measure_mp4(path)   # 缺实测才重测
        else:
            proxy_unavailable_reason = "no_local_file"

    return {
        "video_id": item.video_id, "variant_id": item.variant_id, "group_type": item.group_type,
        "duration": item.duration or (v.duration_seconds if v else None),
        "windows": windows, "transitions": transitions,
        "subtitle_applied": subtitle_applied, "highlight_applied": highlight_applied,
        "cta_applied": cta_applied,
        "visible_style_signature": vstyle_sig or "none", "variation_dimensions": vdims or {},
        "audio_encoding_signature": ae.get("audio_encoding_signature", "off"),
        "eq_profile": ae.get("eq_profile"),
        "audio_encoding": ae,
        "qa": {"playable_ok": qa.get("playable_ok"), "pts_ok": qa.get("pts_ok")},
        "measured": measured,
        "frame_hashes": frame_hashes,
        "_proxy_reason": proxy_unavailable_reason,
    }


def _prev_weight_profile(items: list[P2bExecutionRunItem]) -> str | None:
    """读历史 b3_batch 的 weight_profile（滞后区间用：区间内保持上次）。"""
    for it in items:
        qa = _as_obj(it.qa_json) or {}
        b3b = qa.get("b3_batch")
        if b3b and isinstance(b3b, dict):
            wp = (b3b.get("thresholds_used") or {}).get("weight_profile")
            if wp:
                return wp
    return None


def score_run(db: Session, tenant_id: str, run_id: str, with_frames: bool = True) -> dict:
    """对一个 run（batch）的 done 视频做三维评分并幂等写库。不生成新 mp4、不改 videos.status、cost=0。"""
    if not settings.enable_p2b_b3_score:
        return {"ok": False, "code": 4032, "reason": "B3 评分未开启（ENABLE_P2B_B3_SCORE=false）"}
    run = (db.query(P2bExecutionRun)
           .filter(P2bExecutionRun.run_id == run_id, P2bExecutionRun.tenant_id == tenant_id).first())
    if run is None:
        return {"ok": False, "code": 3001, "reason": "run 不存在或不属于当前租户"}
    items = (db.query(P2bExecutionRunItem)
             .filter(P2bExecutionRunItem.run_id == run_id,
                     P2bExecutionRunItem.tenant_id == tenant_id,
                     P2bExecutionRunItem.status == "done",
                     P2bExecutionRunItem.video_id.isnot(None))
             .order_by(P2bExecutionRunItem.id.asc()).all())
    if len(items) < 2:
        return {"ok": False, "code": 3002, "reason": f"可评分视频不足 2 条（实际 {len(items)}），无法 pairwise"}

    thr = _thr()
    k = thr["keyframes"]
    videos = [_gather_video(db, it, with_frames, k) for it in items]
    prev_profile = _prev_weight_profile(items)

    result = b3_score.score_batch(videos, thr, previous_weight_profile=prev_profile)
    result["batch_id"] = run_id

    # 视觉代理统计（区分 structure_only vs pixel_verified）
    proxy_only = sum(1 for v in videos if v["frame_hashes"] is None)
    result["batch_summary"]["visual_proxy_only_count"] = proxy_only
    result["batch_summary"]["pixel_verified_variant_count"] = len(videos) - proxy_only

    # ---- 幂等写库：videos.meta.b3_score（每条）+ run_items.qa_json.b3_batch（整批）----
    pv_by_id = {p["video_id"]: p for p in result["per_variant"]}
    for it in items:
        v = db.get(Video, it.video_id)
        if v is not None:
            meta = _as_obj(v.meta) or {}
            meta["b3_score"] = {**pv_by_id.get(it.video_id, {}),
                                "batch_id": run_id, "b3_version": thr["b3_version"],
                                "calibration": thr["calibration"]}
            v.meta = json.dumps(meta, ensure_ascii=False)
        qa = _as_obj(it.qa_json) or {}
        qa["b3_batch"] = result          # 幂等：直接覆盖同 key，不追加
        it.qa_json = json.dumps(qa, ensure_ascii=False)
    db.commit()

    return {"ok": True, "data": result}


def get_score(db: Session, tenant_id: str, run_id: str) -> dict | None:
    """读取已写入的 b3_batch（任一 done item 即可）。"""
    it = (db.query(P2bExecutionRunItem)
          .filter(P2bExecutionRunItem.run_id == run_id,
                  P2bExecutionRunItem.tenant_id == tenant_id,
                  P2bExecutionRunItem.status == "done").first())
    if it is None:
        return None
    qa = _as_obj(it.qa_json) or {}
    return qa.get("b3_batch")


def publish_pool(db: Session, tenant_id: str, run_id: str) -> dict:
    """发布池读取契约：只返回 batch_summary.pass=true 且 recommended_action=pass_to_publish_pool 的条目。"""
    b3b = get_score(db, tenant_id, run_id)
    if not b3b:
        return {"run_id": run_id, "eligible": False, "reason": "尚未评分", "videos": []}
    batch_pass = (b3b.get("batch_summary") or {}).get("pass") is True
    eligible = [p for p in (b3b.get("per_variant") or [])
                if p.get("recommended_action") == "pass_to_publish_pool"]
    return {
        "run_id": run_id,
        "eligible": batch_pass and len(eligible) > 0,
        "batch_pass": batch_pass,
        "effective_variant_count": (b3b.get("batch_summary") or {}).get("effective_variant_count", 0),
        "batch_pass_rate": (b3b.get("batch_summary") or {}).get("batch_pass_rate", 0.0),
        "videos": [p["video_id"] for p in eligible] if batch_pass else [],
        "contract": "batch_summary.pass=true AND recommended_action=pass_to_publish_pool",
    }


# ============================ 大 N 模拟（metadata-only，不渲染） ============================

def _synthetic_variants(production_order_id: str, n: int) -> list[dict]:
    """构造 N 条 variant 的 metadata（不渲染）：枚举 6 group×5 index = 30 base，N>30 循环（暴露撞车上限）。

    复用 plan_executor 的确定性算法复算 visible_style_signature / audio_encoding_signature / windows。
    """
    groups = plan_executor._GROUP_TYPE_ORDER
    # 不同 group 用不同镜头序列/时长，逼近真实差异（避免合成数据窗口雷同导致 structure proxy 虚高）
    _ROLE_SEQS = {
        "pain_first":   [("痛点", 1.4), ("产品", 1.0), ("品牌", 0.8)],
        "selling_first":[("卖点", 1.2), ("产品", 1.2), ("效果", 0.9)],
        "result_close": [("效果", 1.3), ("对比", 1.1), ("品牌", 0.7)],
        "brand_double": [("品牌", 1.0), ("产品", 1.0), ("品牌", 1.0)],
        "same_source":  [("产品", 1.1), ("效果", 1.0), ("产品", 0.9)],
        "reverse":      [("效果", 1.2), ("痛点", 1.0), ("产品", 1.0)],
    }
    out = []
    for i in range(n):
        gt = groups[(i // 5) % len(groups)]
        gi = (i % 5) + 1
        variant_id = f"sim_{production_order_id}_{i:04d}"
        seq = _ROLE_SEQS.get(gt, [("产品", 1.2), ("效果", 1.0), ("品牌", 0.8)])
        # group_index 微调时长，使同 group 不同 index 的取窗也分散
        shots = [{"role": r, "duration": round(d * (0.9 + 0.05 * gi), 3)} for r, d in seq]
        vp = {"production_order_id": production_order_id, "group_type": gt, "group_index": gi,
              "rhythm_plan": {"shot_durations": shots,
                              "total_duration": round(sum(s["duration"] for s in shots) * 10, 2)},
              "transition_plan": {"transitions": [{"type": "叠化", "duration": 0.4},
                                                  {"type": "硬切", "duration": 0.0}]}}
        style = plan_executor.resolve_visible_style(vp, variant_id)
        ae = plan_executor.audio_encoding_info(variant_id, run_id="sim")
        plan = plan_executor.derive_windows(vp, 40.0, 25.0, 35.0,
                                            seed=plan_executor._seed_of(variant_id))
        out.append({
            "video_id": i, "variant_id": variant_id, "group_type": gt,
            "windows": plan["windows"], "transitions": plan["transitions"],
            "subtitle_applied": None, "highlight_applied": None, "cta_applied": None,
            "visible_style_signature": style["signature"],
            "variation_dimensions": style["variation_dimensions"],
            "audio_encoding_signature": ae.get("audio_encoding_signature", "off"),
            "eq_profile": ae.get("eq_profile"),
            "frame_hashes": None,   # 模拟无渲染帧 → 视觉走 structural proxy
        })
    return out


def simulate(production_order_id: str, n: int) -> dict:
    """大 N metadata-only 模拟入口（不入库、不渲染、不生成视频、cost=0）。"""
    thr = _thr()
    variants = _synthetic_variants(production_order_id, n)
    sim = b3_score.simulate_large_n(variants, thr, settings.p2b_b3_fullpair_max_n)
    sim["production_order_id"] = production_order_id
    sim["mode"] = "metadata_only_no_render"
    sim["fullpair_max_n"] = settings.p2b_b3_fullpair_max_n
    return sim
