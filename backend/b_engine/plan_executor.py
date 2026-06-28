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
import tempfile
from typing import Any

from b_engine import qa_checks
from config import settings

# 中文字体候选路径（wqy 首选，Noto CJK 作 fallback）。不复用 remixer 的单路径 _font。
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]


def resolve_font() -> dict:
    """三级解析中文字体：settings → 候选路径 → fc-match。返回 {available, font_path, source}。"""
    p = (settings.p2b_subtitle_font_path or "").strip()
    if p and os.path.exists(p):
        return {"available": True, "font_path": p, "source": "settings"}
    for c in _FONT_CANDIDATES:
        if os.path.exists(c):
            return {"available": True, "font_path": c, "source": "candidate"}
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", "sans:lang=zh"],
                           capture_output=True, text=True, timeout=10)
        fp = (r.stdout or "").strip()
        if fp and os.path.exists(fp):
            return {"available": True, "font_path": fp, "source": "fc-match"}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": False, "font_path": None, "source": "none"}


def font_health() -> dict:
    """字体健康（供 runs/preview 返回 visible_layer_ready 使用）。"""
    f = resolve_font()
    return {"visible_layer_ready": bool(f["available"] and settings.enable_p2b_visible_layer),
            "font_available": f["available"], "font_path": f["font_path"],
            "font_source": f["source"], "visible_layer_enabled": settings.enable_p2b_visible_layer}

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


def _seed_of(variant_id: str) -> int:
    """从 variant_id 稳定派生窗口偏移种子（无外部依赖，确定性）。"""
    return sum((i + 1) * ord(ch) for i, ch in enumerate(variant_id or "")) % 997


def derive_windows(vp: dict, src_dur: float, lo: float, hi: float, seed: int = 0) -> dict:
    """从 rhythm_plan + transition_plan 推导：源取窗 + 转场 + 目标时长（含补偿）。

    seed：按 variant 派生的窗口偏移种子，避免同角色窗口重叠 / 不同 variant 取窗雷同（MD5 去重）。
    """
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

    # 源取窗：同角色均分源时长 + jitter微调（避免同角色窗口重叠 + 跨variant不雷同）
    windows = []
    # 统计每个角色出现次数及段序
    role_indices = {}
    for i, r in enumerate(roles):
        role_indices.setdefault(r, []).append(i)
    role_ordinal = [0] * n
    for r, idxs in role_indices.items():
        for seq, idx in enumerate(idxs):
            role_ordinal[idx] = seq

    for i in range(n):
        seg = min(seg_lens[i], max(src_dur, 0.5))
        avail = max(src_dur - seg, 0.0)
        r = roles[i]
        same_count = len(role_indices[r])
        if same_count > 1:
            # 同角色多段：按序均分源时长居中，jitter微调
            slot = src_dur / same_count
            base = slot * (role_ordinal[i] + 0.5) - seg / 2
        else:
            base = _ROLE_ZONE.get(r, _DEFAULT_ZONE) * src_dur - seg / 2
        # 偏移量：由 seed 与段序决定，幅度不超过可用范围
        jitter = (((seed * 31 + i * 17) % 23) / 23.0 - 0.5) * min(seg * 0.3, avail * 0.3)
        start = min(max(base + jitter, 0.0), avail)
        windows.append({"role": r, "start": round(start, 3),
                        "end": round(start + seg, 3), "seg": round(seg, 3)})

    return {"windows": windows, "transitions": exec_trans,
            "target_output": round(target_output, 3), "sum_transition": round(sum_t, 3), "n": n}


def _norm(W: int, H: int, FPS: int) -> str:
    return (f"setpts=PTS-STARTPTS,fps={FPS},"
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def _build_overlays(vp: dict, font_path: str, target: float, text_dir: str) -> tuple[dict, dict]:
    """构建分层叠加层（每条文案单独 textfile，规避中文/特殊字符转义炸 ffmpeg）。

    返回 (layers, applied)：layers = {subtitle:[...], highlight:[...], cta:[...]}（各为 drawtext 列表），
    供分层 fallback 组合（全叠加 → 仅字幕 → 无叠加）。
    """
    layers = {"subtitle": [], "highlight": [], "cta": []}
    applied = {"subtitles": [], "highlight": None, "cta": None}
    counter = {"i": 0}

    def _tf(text: str) -> str:
        counter["i"] += 1
        path = os.path.join(text_dir, f"ov_{counter['i']:02d}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write((text or "").strip())     # 不写换行，避免 drawtext 渲染出空行
        return path

    def _dt(text: str, color: str, size: int, y: str, st: float, en: float) -> str:
        st = max(0.0, min(st, target)); en = max(st + 0.3, min(en, target))
        tf = _tf(text).replace("\\", "/")
        return (f"drawtext=fontfile='{font_path}':textfile='{tf}':fontcolor={color}:"
                f"fontsize={size}:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y={y}:"
                f"enable='between(t,{st:.2f},{en:.2f})'")

    # 字幕：按优先级取前 2（钩子 + 关键）
    entries = sorted(((vp.get("subtitle_plan") or {}).get("subtitle_entries") or []),
                     key=lambda e: str(e.get("priority", "P9")))[:2]
    for e in entries:
        txt = (e.get("text") or "")[:18]
        if not txt:
            continue
        layers["subtitle"].append(
            _dt(txt, "white", 36, "h*0.12", float(e.get("start", 0.3)), float(e.get("end", 2.5))))
        applied["subtitles"].append({"text": txt, "start": e.get("start"), "end": e.get("end")})

    # 高光卡（1 张）：叙事转折点附近
    cards = (vp.get("highlight_card_plan") or {}).get("cards") or []
    if cards:
        c = cards[0]
        txt = (c.get("content") or "")[:18]
        cdur = float(c.get("duration", 1.0) or 1.0)
        st = max(0.5, target * 0.33)
        if txt:
            layers["highlight"].append(_dt(txt, "yellow", 54, "(h-text_h)/2", st, st + cdur))
            applied["highlight"] = {"content": txt, "start": round(st, 2), "duration": cdur}

    # CTA：结尾 2.5s
    cta_txt = (vp.get("cta_plan") or {}).get("text", "")[:18]
    if cta_txt:
        layers["cta"].append(_dt(cta_txt, "yellow", 40, "h-text_h-60", max(0.0, target - 2.5), target))
        applied["cta"] = {"text": cta_txt}

    return layers, applied


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


def _render(src, out, plan, audio, W, H, FPS, overlays) -> None:
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(_build_cmd(src, out, plan, audio, W, H, FPS, overlays),
                   check=True, capture_output=True, timeout=300)


def execute_plan(src: str, src_dur: float, audio: bool, out: str, variant_plan: Any,
                 W: int, H: int, FPS: int, lo: float, hi: float, tol: float,
                 batch_md5: set[str], variant_id: str = "") -> dict:
    """执行单条计划 → 真实 mp4 + QA。返回 {ok, qa, plan, applied, fallbacks}。

    可见层（P2B-B2）：字体三级解析 + textfile drawtext + 分层 fallback（全叠加→仅字幕→无叠加）；
    SRT sidecar 只要有字幕就输出。底座（取窗/转场/音频/QA）一律不变。
    variant_id：派生窗口偏移种子，保证同批取窗差异化、MD5 唯一。
    """
    vp = _as_obj(variant_plan)
    plan = derive_windows(vp, src_dur, lo, hi, seed=_seed_of(variant_id))
    target = plan["target_output"]
    font = resolve_font()

    # SRT sidecar：只要 subtitle_plan 有内容就输出（烧录成功也输出）
    has_sub = bool((vp.get("subtitle_plan") or {}).get("subtitle_entries"))
    srt_written = False
    if has_sub:
        _write_srt(os.path.splitext(out)[0] + ".srt", vp)
        srt_written = True

    applied = {"subtitles": [], "highlight": None, "cta": None}
    fallbacks = {"subtitle_burned": False, "highlight_burned": False, "cta_burned": False,
                 "font_path": font["font_path"], "font_source": font["source"],
                 "visible_layer_enabled": bool(settings.enable_p2b_visible_layer),
                 "srt": srt_written, "fallback_reason": ""}

    if not settings.enable_p2b_visible_layer:
        fallbacks["fallback_reason"] = "visible_layer_disabled"
        _render(src, out, plan, audio, W, H, FPS, [])
    elif not font["available"]:
        fallbacks["fallback_reason"] = "no_font"
        _render(src, out, plan, audio, W, H, FPS, [])
    else:
        text_dir = tempfile.mkdtemp()
        layers, applied_all = _build_overlays(vp, font["font_path"], target, text_dir)
        # 分层降级：全叠加 → 仅字幕 → 无叠加（逐级回退，不一失败就全跳过）
        tiers = [
            ("full", layers["subtitle"] + layers["highlight"] + layers["cta"],
             {"subtitle": bool(layers["subtitle"]), "highlight": bool(layers["highlight"]), "cta": bool(layers["cta"])}),
            ("subtitle_only", layers["subtitle"],
             {"subtitle": bool(layers["subtitle"]), "highlight": False, "cta": False}),
            ("none", [], {"subtitle": False, "highlight": False, "cta": False}),
        ]
        for name, ov, burned in tiers:
            try:
                _render(src, out, plan, audio, W, H, FPS, ov)
            except subprocess.CalledProcessError:
                continue
            fallbacks["subtitle_burned"] = burned["subtitle"]
            fallbacks["highlight_burned"] = burned["highlight"]
            fallbacks["cta_burned"] = burned["cta"]
            if name != "full":
                fallbacks["fallback_reason"] = f"degraded_to_{name}"
            applied = {
                "subtitles": applied_all["subtitles"] if burned["subtitle"] else [],
                "highlight": applied_all["highlight"] if burned["highlight"] else None,
                "cta": applied_all["cta"] if burned["cta"] else None,
            }
            break

    qa = qa_checks.run_gates(out, batch_md5, lo, hi, tol)
    return {"ok": qa["final_status"] == "pass", "qa": qa, "plan": plan,
            "applied": applied, "fallbacks": fallbacks}
