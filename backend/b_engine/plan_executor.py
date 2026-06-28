"""P2B-B1 计划执行器（V4 P2B-B1 · 把 P2B-A 后期脑子翻译成真实 ffmpeg）。

读取 P2B-A variant_plan 的 6 个工艺计划，确定性翻译为本地 ffmpeg 参数并真实成片：
- rhythm_plan   → 按时长比例确定性切窗（含转场补偿：原始片段总长 = 目标时长 + Σ转场时长）
- transition_plan → 真实视觉转场（hard_cut/fade/dissolve/smooth_fade，中文→执行映射）
  · A/V 同步铁律：每个拼接点 视频 xfade duration == 音频 acrossfade duration
- subtitle/highlight_card/cta → 轻量 drawtext，可降级（字体缺失/渲染失败 → 不卡死主流程）
- uniqueness   → 不同 variant 段序/转场/字幕不同 → MD5 唯一

零 LLM、零火山、零成本；复用 b_engine.qa_checks 四道 hard gate。不修改 remixer 既有路径。
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from b_engine import qa_checks
from b_engine.remixer import _esc, _font

# 中文转场 → (xfade transition 名 | None 表示 hard_cut)
_TRANSITION_EXEC = {
    "快切": (None, "hard_cut"),
    "交叉淡化": ("fade", "fade"),
    "溶解": ("dissolve", "dissolve"),
    "擦除": ("dissolve", "dissolve"),      # 首版降级为 dissolve（不做 wipe 模板库）
    "淡入": ("fadeblack", "smooth_fade"),
    "淡出淡入": ("fadeblack", "smooth_fade"),
}
_DEFAULT_TRANSITION = ("fade", "fade")

# 中文镜头角色 → 源视频取窗位置（0-1 比例）。重复角色取同位（差异化靠段序/转场/字幕）。
_ROLE_ZONE = {
    "痛点": 0.06, "产品": 0.30, "解决方案": 0.45, "效果": 0.62, "品牌": 0.83, "行动号召": 0.95,
}
_DEFAULT_ZONE = 0.5
_EPS = 0.40          # 原始片段总长冗余，保证 -t 裁剪后落区间
_MAX_XFADE = 0.6     # 单次转场上限


def _as_obj(variant_plan: Any) -> dict:
    """variant_plan 兼容 string / object / 缺失。"""
    if isinstance(variant_plan, str):
        try:
            return json.loads(variant_plan)
        except (ValueError, TypeError):
            return {}
    return variant_plan or {}


def _exec_transition(cn_type: str, plan_d: float) -> tuple[str | None, str, float]:
    """中文转场 → (xfade_name|None, exec_label, duration)。hard_cut → (None, 'hard_cut', 0)。"""
    xname, label = _TRANSITION_EXEC.get(cn_type, _DEFAULT_TRANSITION)
    if label == "hard_cut" or xname is None:
        return None, "hard_cut", 0.0
    d = plan_d if plan_d and plan_d > 0 else (0.5 if label == "smooth_fade" else 0.4)
    return xname, label, float(d)


def derive_windows(vp: dict, src_dur: float, lo: float, hi: float) -> dict:
    """从 rhythm_plan + transition_plan 推导：源取窗 + 转场 + 目标时长（含补偿）。"""
    rhythm = vp.get("rhythm_plan") or {}
    shots = rhythm.get("shot_durations") or []
    if not shots:
        # fallback：用 narrative_structure 均分
        roles = vp.get("narrative_structure") or ["产品", "产品", "品牌"]
        shots = [{"role": r, "duration": 1.0} for r in roles]
    roles = [s.get("role", "产品") for s in shots]
    plan_durs = [max(float(s.get("duration", 1.0)), 0.1) for s in shots]
    n = len(shots)

    # 目标输出时长：rhythm 总长 → 钳到 [lo,hi]，并不超过源能支撑
    base_total = float(rhythm.get("total_duration") or sum(plan_durs))
    target_output = max(lo, min(hi, base_total))
    target_output = min(target_output, max(lo, src_dur - 0.5))

    # 转场（n-1 个）→ 执行参数
    trans_in = (vp.get("transition_plan") or {}).get("transitions") or []
    exec_trans = []
    for k in range(n - 1):
        t = trans_in[k] if k < len(trans_in) else {}
        xname, label, d = _exec_transition(t.get("type", ""), float(t.get("duration", 0) or 0))
        exec_trans.append({"from_role": roles[k], "to_role": roles[k + 1],
                           "type_cn": t.get("type", ""), "exec": label, "xfade": xname, "duration": d})
    sum_t = sum(e["duration"] for e in exec_trans)

    # 转场补偿：原始片段总长 = 目标 + Σ转场 + 冗余
    raw_total = target_output + sum_t + _EPS
    dsum = sum(plan_durs) or 1.0
    seg_lens = [max(plan_durs[i] / dsum * raw_total, 0.4) for i in range(n)]

    # 源取窗：按角色 zone 居中
    windows = []
    for i in range(n):
        seg = min(seg_lens[i], max(src_dur, 0.5))
        center = _ROLE_ZONE.get(roles[i], _DEFAULT_ZONE) * src_dur
        start = min(max(center - seg / 2, 0.0), max(src_dur - seg, 0.0))
        windows.append({"role": roles[i], "start": round(start, 3),
                        "end": round(start + seg, 3), "seg": round(seg, 3)})

    return {"windows": windows, "transitions": exec_trans,
            "target_output": round(target_output, 3), "sum_transition": round(sum_t, 3), "n": n}


def _norm(W: int, H: int, FPS: int) -> str:
    return (f"setpts=PTS-STARTPTS,fps={FPS},"
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def _overlay_filters(vp: dict, font: str, target: float) -> tuple[list[str], dict]:
    """字幕(1-3) + 高光卡(1) + CTA → drawtext 列表。返回 (filters, applied)。"""
    applied = {"subtitles": [], "highlight": None, "cta": None}
    parts = []

    def _dt(text, color, size, y, st, en):
        st = max(0.0, min(st, target)); en = max(st + 0.3, min(en, target))
        return (f"drawtext=fontfile='{font}':text='{_esc(text)}':fontcolor={color}:"
                f"fontsize={size}:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y={y}:"
                f"enable='between(t,{st:.2f},{en:.2f})'")

    # 字幕：按优先级取前 2（钩子 + 关键），品牌字幕单列
    sub = (vp.get("subtitle_plan") or {})
    entries = sorted((sub.get("subtitle_entries") or []),
                     key=lambda e: str(e.get("priority", "P9")))[:2]
    for e in entries:
        txt = (e.get("text") or "")[:18]
        if not txt:
            continue
        parts.append(_dt(txt, "white", 36, "h*0.12", float(e.get("start", 0.3)), float(e.get("end", 2.5))))
        applied["subtitles"].append({"text": txt, "start": e.get("start"), "end": e.get("end")})

    # 高光卡（1 张）：叙事转折点附近
    cards = (vp.get("highlight_card_plan") or {}).get("cards") or []
    if cards:
        c = cards[0]
        txt = (c.get("content") or "")[:18]
        cdur = float(c.get("duration", 1.0) or 1.0)
        st = max(0.5, target * 0.33)
        if txt:
            parts.append(_dt(txt, "yellow", 54, "(h-text_h)/2", st, st + cdur))
            applied["highlight"] = {"content": txt, "start": round(st, 2), "duration": cdur}

    # CTA：结尾 2.5s
    cta = vp.get("cta_plan") or {}
    cta_txt = (cta.get("text") or "")[:18]
    if cta_txt:
        parts.append(_dt(cta_txt, "yellow", 40, "h-text_h-60", max(0.0, target - 2.5), target))
        applied["cta"] = {"text": cta_txt}

    return parts, applied


def _build_cmd(src: str, out: str, plan: dict, audio: bool, W: int, H: int, FPS: int,
               overlays: list[str]) -> list[str]:
    """组装单条 ffmpeg 命令（视频 xfade/concat + 音频 acrossfade/concat + 叠加层）。"""
    windows = plan["windows"]
    trans = plan["transitions"]
    target = plan["target_output"]
    n = len(windows)
    norm = _norm(W, H, FPS)
    fc: list[str] = []

    inputs = ["-i", src]
    for k, w in enumerate(windows):
        fc.append(f"[0:v]trim=start={w['start']:.3f}:end={w['end']:.3f},{norm}[v{k}]")
        if audio:
            fc.append(f"[0:a]atrim=start={w['start']:.3f}:end={w['end']:.3f},asetpts=PTS-STARTPTS,"
                      f"aresample=async=1:first_pts=0[a{k}]")

    acc_v, acc_a = "v0", "a0"
    cur = windows[0]["seg"]
    for k in range(1, n):
        e = trans[k - 1]
        seg_k = windows[k]["seg"]
        d = e["duration"]
        d = min(d, seg_k * 0.5 - 0.01, cur * 0.5, _MAX_XFADE) if d > 0 else 0.0
        if e["xfade"] is None or d <= 0:                    # hard cut → concat
            nv = f"cv{k}"; fc.append(f"[{acc_v}][v{k}]concat=n=2:v=1:a=0[{nv}]"); acc_v = nv
            if audio:
                na = f"ca{k}"; fc.append(f"[{acc_a}][a{k}]concat=n=2:v=0:a=1[{na}]"); acc_a = na
            cur += seg_k
            e["applied_duration"] = 0.0
        else:                                               # xfade(视频) + acrossfade(音频) 同 d
            off = max(cur - d, 0.0)
            nv = f"xv{k}"
            fc.append(f"[{acc_v}][v{k}]xfade=transition={e['xfade']}:duration={d:.3f}:offset={off:.3f}[{nv}]")
            acc_v = nv
            if audio:
                na = f"xa{k}"
                fc.append(f"[{acc_a}][a{k}]acrossfade=d={d:.3f}:c1=tri:c2=tri[{na}]")
                acc_a = na
            cur = cur + seg_k - d
            e["applied_duration"] = round(d, 3)

    # 叠加层（可空）
    if overlays:
        fc.append(f"[{acc_v}]" + ",".join(overlays) + "[vout]")
    else:
        fc.append(f"[{acc_v}]null[vout]")

    # 音频：无音轨 → anullsrc 补静音
    if audio:
        a_label = f"[{acc_a}]"
    else:
        inputs += ["-f", "lavfi", "-t", f"{target + 1.0:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        fc.append(f"[1:a]atrim=0:{target:.2f},asetpts=PTS-STARTPTS[ac]")
        a_label = "[ac]"

    return ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
            "-map", "[vout]", "-map", a_label, "-t", f"{target:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", out]


def _write_srt(path: str, vp: dict) -> None:
    """字幕降级：drawtext 不可用时输出 sidecar .srt。"""
    entries = (vp.get("subtitle_plan") or {}).get("subtitle_entries") or []
    def _ts(t):
        t = max(0.0, float(t)); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
    lines = []
    for i, e in enumerate(entries[:3], 1):
        lines.append(f"{i}\n{_ts(e.get('start',0))} --> {_ts(e.get('end',2))}\n{e.get('text','')}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def execute_plan(src: str, src_dur: float, audio: bool, out: str, variant_plan: Any,
                 W: int, H: int, FPS: int, lo: float, hi: float, tol: float,
                 batch_md5: set[str]) -> dict:
    """执行单条计划 → 真实 mp4 + QA。返回 {ok, qa, plan, applied, fallbacks}。"""
    vp = _as_obj(variant_plan)
    plan = derive_windows(vp, src_dur, lo, hi)
    font = _font()
    fallbacks = {"subtitle": False, "highlight": False, "cta": False, "overlay_render": False}

    # 字体缺失 → 全部叠加层降级（字幕走 sidecar srt）
    if font:
        overlays, applied = _overlay_filters(vp, font, plan["target_output"])
    else:
        overlays, applied = [], {"subtitles": [], "highlight": None, "cta": None}
        fallbacks.update(subtitle=True, highlight=True, cta=True)
        _write_srt(os.path.splitext(out)[0] + ".srt", vp)

    # 主路径：带叠加层；失败 → 去叠加层重试（主视频不被轻量视觉层卡死）
    try:
        subprocess.run(_build_cmd(src, out, plan, audio, W, H, FPS, overlays),
                       check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError:
        if os.path.exists(out):
            os.remove(out)
        fallbacks.update(overlay_render=True, subtitle=True, highlight=True, cta=True)
        if not os.path.splitext(out)[0].endswith(".srt"):
            _write_srt(os.path.splitext(out)[0] + ".srt", vp)
        applied = {"subtitles": [], "highlight": None, "cta": None}
        subprocess.run(_build_cmd(src, out, plan, audio, W, H, FPS, []),
                       check=True, capture_output=True, timeout=300)

    qa = qa_checks.run_gates(out, batch_md5, lo, hi, tol)
    return {"ok": qa["final_status"] == "pass", "qa": qa, "plan": plan,
            "applied": applied, "fallbacks": fallbacks}
