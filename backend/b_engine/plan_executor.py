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

import hashlib
import json
import os
import re
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


# ============================================================
# P2B-B2.1：可见层逐 variant 确定性差异化（ASS 档位）
# ============================================================
# ASS PlayResY 基准（与 _write_ass 头部一致）；所有尺寸量按「占画高百分比 × PLAY_RES_Y」定义，
# libass 自动按实际分辨率缩放 → 多分辨率「不出框」（必改4）。
_PLAY_RES_Y = 1280
_GROUP_TYPE_ORDER = ["pain_first", "selling_first", "result_close",
                     "brand_double", "same_source", "reverse"]

# 9 个可见层维度的离散档位（强可感 3 维：subtitle_alignment / cta_style / highlight_time_bucket）
_SA_OPTS = [8, 2, 5]                       # 字幕对齐：顶/底/中（中=5 为短钩子保留，见红线）
_CS_OPTS = ["yellow", "white", "box", "noborder"]   # CTA 样式（强可感）
_HT_OPTS = [0.20, 0.33, 0.50]             # 高光卡出现时间（占 target；强可感）
_MV_OPTS = [0.09, 0.12, 0.15]             # 字幕 MarginV（占画高）
_FS_OPTS = [0.030, 0.034, 0.038]          # 字幕字号（占画高）
_OL_OPTS = [1.5, 2.0, 2.5]                # 字幕描边
_HA_OPTS = [5, 8, 2]                      # 高光卡对齐：中/偏上/偏下
_CA_OPTS = [(2, 0.047), (2, 0.086), (2, 0.148)]     # CTA 对齐+MarginV：底/偏底/中下
_CD_OPTS = [2.0, 2.5, 3.0]                # CTA 出现时长（结尾秒数）

# B2 固定版式（fallback 中间档；含必改3：保留强可感 subtitle_alignment + cta_duration）
_FIXED_STYLE = {
    "subtitle_alignment": 8, "subtitle_margin_v_px": int(0.094 * _PLAY_RES_Y),
    "subtitle_font_size_px": int(0.0281 * _PLAY_RES_Y), "subtitle_outline": 2.0,
    "highlight_alignment": 5, "highlight_time_frac": 0.33,
    "cta_alignment": 2, "cta_margin_v_px": int(0.047 * _PLAY_RES_Y),
    "cta_style": "yellow", "cta_duration": 2.5,
    "signature": "fixed", "variation_dimensions": {}, "variation_seed": 0,
}


def _variation_seed(vp: dict, variant_id: str) -> int:
    """增强 seed（必改2）：variant_id 为主 + production_order_id 二级扰动（扩值域、降撞档）。"""
    key = f"{vp.get('production_order_id', '')}|{variant_id}"
    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


def _variant_index(vp: dict, vseed: int) -> int:
    """0..29 唯一变体序（group_order×5 + group_index-1）；缺字段则退回 vseed%30。"""
    gt, gi = vp.get("group_type"), vp.get("group_index")
    if gt in _GROUP_TYPE_ORDER and isinstance(gi, int) and 1 <= gi <= 5:
        return _GROUP_TYPE_ORDER.index(gt) * 5 + (gi - 1)
    return vseed % 30


def resolve_visible_style(vp: dict, variant_id: str) -> dict:
    """逐 variant 确定性解析 9 维 ASS 档位 + visible_style_signature（确定性、可复算）。

    强可感 3 维（subtitle_alignment / cta_style / highlight_time）由 vidx 混合进制编码，
    保证「任意两条不同 vidx → 强可感三元组不同」（必改1）；弱 6 维由增强 seed 互异质数取档。
    """
    vseed = _variation_seed(vp, variant_id)
    vidx = _variant_index(vp, vseed)
    # 强可感（vidx 混合进制：a∈0..2, b∈0..3, c∈0..2 唯一编码 0..35 ⊇ 0..29）
    sa, cs, ht = vidx % 3, (vidx // 3) % 4, (vidx // 12) % 3
    # 弱维（互异质数偏移，半独立）
    mv, fs, ol = (vseed // 3) % 3, (vseed // 7) % 3, (vseed // 13) % 3
    ha, ca, cd = (vseed // 17) % 3, (vseed // 23) % 3, (vseed // 29) % 3

    cta_align, cta_mv_frac = _CA_OPTS[ca]
    dims = {
        "subtitle_alignment": _SA_OPTS[sa], "subtitle_margin_v": _MV_OPTS[mv],
        "subtitle_font_size": _FS_OPTS[fs], "subtitle_outline": _OL_OPTS[ol],
        "highlight_alignment": _HA_OPTS[ha], "highlight_time_bucket": _HT_OPTS[ht],
        "cta_alignment": cta_align, "cta_style": _CS_OPTS[cs], "cta_duration_bucket": _CD_OPTS[cd],
    }
    signature = f"sa{sa}mv{mv}fs{fs}ol{ol}ha{ha}ht{ht}ca{ca}cs{cs}cd{cd}"
    return {
        "subtitle_alignment": _SA_OPTS[sa],
        "subtitle_margin_v_px": int(_MV_OPTS[mv] * _PLAY_RES_Y),
        "subtitle_font_size_px": int(_FS_OPTS[fs] * _PLAY_RES_Y),
        "subtitle_outline": _OL_OPTS[ol],
        "highlight_alignment": _HA_OPTS[ha], "highlight_time_frac": _HT_OPTS[ht],
        "cta_alignment": cta_align, "cta_margin_v_px": int(cta_mv_frac * _PLAY_RES_Y),
        "cta_style": _CS_OPTS[cs], "cta_duration": _CD_OPTS[cd],
        "signature": signature, "variation_dimensions": dims, "variation_seed": vseed,
        "strong_dims": {"subtitle_alignment": sa, "cta_style": cs, "highlight_time_bucket": ht},
    }


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


_STRONG_DIMS = {"subtitle_alignment", "cta_style", "highlight_time_bucket"}


def batch_variation_audit(specs: list[dict]) -> dict:
    """批次内档位组合唯一性/差异度自检（必改2 撞档校验）。

    specs：[{variant_id, production_order_id?, group_type?, group_index?}, ...]
    返回：signatures、unique、min_pairwise_dims、min_pairwise_strong、batch_covered_dims、
    violations（任意两条 <3 维 或 强可感无差异 的对）、collisions（≥7 维相同的对）。
    """
    import itertools
    rows = []
    for s in specs:
        vp = {"production_order_id": s.get("production_order_id", ""),
              "group_type": s.get("group_type"), "group_index": s.get("group_index")}
        st = resolve_visible_style(vp, s.get("variant_id", ""))
        rows.append((s.get("variant_id", ""), st))
    dk = list((rows[0][1]["variation_dimensions"]).keys()) if rows else []
    sigs = [st["signature"] for _, st in rows]
    min_dims, min_strong = 9, 9
    violations, collisions = [], []
    for (v1, s1), (v2, s2) in itertools.combinations(rows, 2):
        diff = [k for k in dk if s1["variation_dimensions"][k] != s2["variation_dimensions"][k]]
        strong = [k for k in diff if k in _STRONG_DIMS]
        min_dims = min(min_dims, len(diff)); min_strong = min(min_strong, len(strong))
        if len(diff) < 3 or len(strong) < 1:
            violations.append((v1, v2, len(diff), len(strong)))
        if (len(dk) - len(diff)) >= 7:
            collisions.append((v1, v2))
    covered = [k for k in dk if len({st["variation_dimensions"][k] for _, st in rows}) > 1]
    return {"signatures": sigs, "unique": len(set(sigs)) == len(sigs),
            "min_pairwise_dims": (min_dims if rows else 0),
            "min_pairwise_strong": (min_strong if rows else 0),
            "batch_covered_dims": len(covered), "covered": covered,
            "violations": violations, "collisions": collisions}


# CTA 样式 → (PrimaryColour, BorderStyle, Outline, BackColour)
_CTA_STYLE_ASS = {
    "yellow":   ("&H0000FFFF", 1, 2.0, "&H80000000"),
    "white":    ("&H00FFFFFF", 1, 2.0, "&H80000000"),
    "box":      ("&H0000FFFF", 3, 2.0, "&H80000000"),   # BorderStyle=3 不透明框底
    "noborder": ("&H0000FFFF", 1, 0.0, "&H00000000"),   # 无描边
}


def _write_ass(path: str, entries: list, style_name: str, font_path: str,
               fontsize: int, primary_color: str, alignment: int, margin_v: int,
               outline: float = 2.0, border_style: int = 1, back_color: str = "&H80000000") -> str | None:
    """写一个 ASS 文件（参数全部正确注入；修复 b86dbb6 中 {alignment}/{margin_v} 未替换的隐患）。"""
    if not entries:
        return None

    def _ts(t: float) -> str:
        t = max(0.0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    style = (f"Style: {style_name},{os.path.basename(font_path)},{fontsize},{primary_color},"
             f"&H000000FF,&H00000000,{back_color},-1,0,0,0,100,100,0,0,"
             f"{border_style},{outline:.1f},1,{alignment},10,10,{margin_v},1")
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 720", f"PlayResY: {_PLAY_RES_Y}",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for e in entries:
        txt = e["text"].replace("\\N", " ").replace("\\n", " ").replace("\n", " ")
        lines.append(f"Dialogue: 0,{_ts(e['start'])},{_ts(e['end'])},{style_name},,0,0,0,,{txt}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _build_overlays(vp: dict, font_path: str, target: float, text_dir: str, style: dict) -> tuple[dict, dict]:
    """构建分层 ASS 叠加层（按 style 档位差异化）。返回 (layers, applied)。

    style 来自 resolve_visible_style（差异化）或 _FIXED_STYLE（B2 固定）。中部字幕(5)按红线限 ≤2s。
    """
    layers = {"subtitle": [], "highlight": [], "cta": []}
    applied = {"subtitles": [], "highlight": None, "cta": None,
               "visible_style_signature": style["signature"],
               "variation_seed": style.get("variation_seed", 0),
               "variation_dimensions": style.get("variation_dimensions", {})}

    # 字幕（前 2 条）
    sub_entries = sorted(((vp.get("subtitle_plan") or {}).get("subtitle_entries") or []),
                         key=lambda e: str(e.get("priority", "P9")))[:2]
    sub_align = style["subtitle_alignment"]
    sub_rows = []
    for e in sub_entries:
        txt = (e.get("text") or "")[:18]
        if not txt:
            continue
        st = max(0.0, float(e.get("start", 0.3)))
        en = min(target, float(e.get("end", 2.5)))
        if sub_align == 5:                      # 红线：中部字幕仅短钩子，限 ≤2s
            en = min(en, st + 2.0)
        sub_rows.append({"start": st, "end": en, "text": txt})
        applied["subtitles"].append({"text": txt, "start": e.get("start"), "end": e.get("end"),
                                     "alignment": sub_align})
    if sub_rows:
        p = _write_ass(os.path.join(text_dir, "subtitle.ass"), sub_rows, "Sub", font_path,
                       style["subtitle_font_size_px"], "&H00FFFFFF", sub_align,
                       style["subtitle_margin_v_px"], outline=style["subtitle_outline"])
        if p:
            layers["subtitle"].append(p)

    # 高光卡（1 张）：时间档位 + 对齐档位
    cards = (vp.get("highlight_card_plan") or {}).get("cards") or []
    if cards:
        c = cards[0]
        txt = (c.get("content") or "")[:18]
        cdur = float(c.get("duration", 1.0) or 1.0)
        st = max(0.5, target * style["highlight_time_frac"])
        if txt:
            p = _write_ass(os.path.join(text_dir, "highlight.ass"),
                           [{"start": st, "end": min(target, st + cdur), "text": txt}],
                           "HL", font_path, int(0.042 * _PLAY_RES_Y), "&H0000FFFF",
                           style["highlight_alignment"], 0)
            if p:
                layers["highlight"].append(p)
            applied["highlight"] = {"content": txt, "start": round(st, 2), "duration": cdur,
                                    "alignment": style["highlight_alignment"]}

    # CTA：时长档位 + 样式档位 + 对齐档位
    cta_txt = (vp.get("cta_plan") or {}).get("text", "")[:18]
    if cta_txt:
        cta_st = max(0.0, target - style["cta_duration"])
        pc, bs, ol, bc = _CTA_STYLE_ASS.get(style["cta_style"], _CTA_STYLE_ASS["yellow"])
        p = _write_ass(os.path.join(text_dir, "cta.ass"),
                       [{"start": cta_st, "end": target, "text": cta_txt}],
                       "CTA", font_path, int(0.031 * _PLAY_RES_Y), pc,
                       style["cta_alignment"], style["cta_margin_v_px"],
                       outline=ol, border_style=bs, back_color=bc)
        if p:
            layers["cta"].append(p)
        applied["cta"] = {"text": cta_txt, "style": style["cta_style"],
                          "duration": style["cta_duration"], "alignment": style["cta_alignment"]}

    return layers, applied


# ============================================================
# P2B-B2.5：音频/编码合规差异化（响度规范化 + 逐 variant 轻 EQ + metadata 清理 + 诚实溯源）
# 合规口径：授权范围内自然差异 + 诚实溯源；禁止防搬运/破检测/伪造来源/伪造设备。
# ============================================================
# 逐 variant 轻 EQ profile（幅度 ≤ ±1.5 dB，不改时长/音高，不破音）
_EQ_PROFILES = [
    ("neutral", "anull"),                                   # 中性（不改音色）
    ("warm_low_shelf", "bass=g=1.5:f=110"),                 # 暖：低频 shelf +1.5 dB
    ("clear_presence", "equalizer=f=3000:t=q:w=1.5:g=1.5"), # 清晰：中高频 presence +1.5 dB
    ("soft_high_shelf", "treble=g=-1.5:f=8000"),            # 柔和：高频 shelf -1.5 dB
]
# B 级变速 / C 级变调：本阶段禁止启用，仅预留常量（不得在命令中实际使用）
_TEMPO_RESERVED = 1.0      # atempo 预留（B2.5 不启用）
_PITCH_RESERVED = 1.0      # 变调预留（B2.5 禁止）
_ENC_PROFILE = "libx264:veryfast:yuv420p:aac:44100:stereo:+faststart"


def _audio_eq_profile(variant_id: str) -> tuple[int, str, str]:
    """逐 variant 确定性选 EQ profile。返回 (idx, name, filter)。"""
    idx = _variation_seed({}, variant_id) % len(_EQ_PROFILES)
    name, flt = _EQ_PROFILES[idx]
    return idx, name, flt


def _provenance(run_id: str) -> str:
    """诚实溯源串（不伪造设备/不冒充第三方/标注 AI 生成）。"""
    commit = (settings.p2b_build_commit or "unknown")
    return (f"generated_by=meiye_v4_p2b;module=p2b_b2_5;run_id={run_id or 'na'};"
            f"source=authorized_material;ai_generated=true;commit={commit}")


def audio_encoding_info(variant_id: str, run_id: str = "") -> dict:
    """计算本条音频/编码合规差异化信息 + audio_encoding_signature（确定性、可复算）。"""
    if not settings.enable_p2b_audio_encoding_diff:
        return {"applied": False, "audio_encoding_signature": "off"}
    eq_idx, eq_name, eq_flt = _audio_eq_profile(variant_id)
    prov = _provenance(run_id)
    prov_hash = hashlib.md5(prov.encode("utf-8")).hexdigest()[:8]
    var_hash = hashlib.md5((variant_id or "").encode("utf-8")).hexdigest()[:6]
    # signature 仅由「处理口径 + variant 身份」决定（不含 run_id），保证同 variant 跨 run 一致；
    # provenance_hash（含 run_id）单独记录在 info 中，不进 signature。
    sig = (f"lufs{settings.p2b_loudness_target_lufs:g}tp{settings.p2b_true_peak_dbtp:g}"
           f"eq{eq_idx}:{eq_name}|enc:{_ENC_PROFILE}|mc1|var{var_hash}")
    return {
        "applied": True,
        "target_lufs": settings.p2b_loudness_target_lufs,
        "true_peak_target_dbtp": settings.p2b_true_peak_dbtp,
        "loudnorm_pass": "two",             # 两趟 loudnorm（analyze + linear apply），EQ 前置
        "eq_profile": eq_name, "eq_index": eq_idx, "eq_filter": eq_flt,
        "tempo_factor": _TEMPO_RESERVED,    # 1.0：B2.5 不变速
        "encoding_profile": _ENC_PROFILE,
        "metadata_cleaned": True,
        "provenance": prov, "provenance_hash": prov_hash,
        "audio_encoding_signature": sig,
    }


def _build_cmd(src: str, out: str, plan: dict, audio: bool, W: int, H: int, FPS: int,
               overlays: list[str]) -> list[str]:
    """组装单条 ffmpeg 命令（视频 xfade/concat + 音频 acrossfade/concat + 叠加层）。

    B2.5 的音频/编码后处理不在此（见 _apply_audio_encoding 第二趟），保持拼接 filter_complex 干净。
    """
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

    # 叠加层（可空）：subtitles 滤镜需逐级串联
    if overlays:
        cur_v = acc_v
        for idx, ov in enumerate(overlays):
            nv = f"ov{idx}" if idx < len(overlays) - 1 else "vout"
            fc.append(f"[{cur_v}]{ov}[{nv}]")
            cur_v = nv
        if cur_v != "vout":
            fc.append(f"[{cur_v}]null[vout]")
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


_LRA = 11.0   # loudnorm Loudness Range 目标


def _loudnorm_analyze(path: str, eq: str, lufs: float, tp: float) -> dict | None:
    """两趟 loudnorm 第一趟：EQ → loudnorm(print_format=json) 测量。返回 measured 字典或 None。"""
    af = f"{eq},loudnorm=I={lufs:g}:TP={tp:g}:LRA={_LRA:g}:print_format=json"
    r = subprocess.run(["ffmpeg", "-i", path, "-map", "0:a", "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True, timeout=180)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return None
    try:
        return json.loads(m[-1])
    except ValueError:
        return None


def _apply_audio_encoding(path: str, audio_enc: dict) -> None:
    """B2.5 第二/第三趟（audio-only，-c:v copy）：两趟 loudnorm（EQ 前置）+ metadata 清理 + 诚实溯源。

    链路：EQ → loudnorm analyze（测量）→ loudnorm apply(linear，按测量值精确达标) → AAC 导出。
    EQ 放 loudnorm 之前，避免 EQ 改变最终响度；linear 模式按测量值线性规范，稳定达到 -14 LUFS±1、TP ≤ -1。
    `-c:v copy` 不重编码视频、不改时长/不变速/不变调。loudnorm 不与 acrossfade 同图（避免偶发卡死）。
    """
    if not (audio_enc and audio_enc.get("applied")):
        return
    lufs = audio_enc["target_lufs"]; tp = audio_enc["true_peak_target_dbtp"]
    eq = audio_enc.get("eq_filter") or "anull"

    meas = _loudnorm_analyze(path, eq, lufs, tp)
    if meas:
        # 第二趟：linear 模式 + 测量值 → 精确达标（EQ 仍前置，保证测量一致）
        ln = (f"loudnorm=I={lufs:g}:TP={tp:g}:LRA={_LRA:g}:linear=true:"
              f"measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
              f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
              f"offset={meas.get('target_offset', '0.0')}")
    else:
        # 兜底：测量失败回退单趟 dynamic（EQ 仍前置）
        ln = f"loudnorm=I={lufs:g}:TP={tp:g}:LRA={_LRA:g}"
    af = f"{eq},{ln},aformat=sample_rates=44100:channel_layouts=stereo"

    tmp = path + ".aenc.mp4"
    cmd = ["ffmpeg", "-y", "-i", path, "-map", "0:v", "-map", "0:a", "-c:v", "copy",
           "-af", af, "-c:a", "aac", "-ar", "44100", "-ac", "2",
           "-map_metadata", "-1", "-metadata", f"comment={audio_enc['provenance']}",
           "-movflags", "+faststart", tmp]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    os.replace(tmp, path)


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
                 batch_md5: set[str], variant_id: str = "", run_id: str = "") -> dict:
    """执行单条计划 → 真实 mp4 + QA。返回 {ok, qa, plan, applied, fallbacks, audio_encoding}。

    可见层（B2/B2.1）：ASS 差异化 + 分层 fallback + SRT；音频/编码（B2.5）：响度规范化 + 轻 EQ +
    metadata 清理 + 诚实溯源（叠加在拼接之后，不改 acrossfade/取窗/转场/QA）。
    variant_id：派生取窗/可见层/EQ 种子；run_id：诚实溯源 provenance。
    """
    vp = _as_obj(variant_plan)
    plan = derive_windows(vp, src_dur, lo, hi, seed=_seed_of(variant_id))
    target = plan["target_output"]
    font = resolve_font()
    audio_enc = audio_encoding_info(variant_id, run_id)   # B2.5（flag 关 → applied=False）

    # SRT sidecar：只要 subtitle_plan 有内容就输出（烧录成功也输出）
    has_sub = bool((vp.get("subtitle_plan") or {}).get("subtitle_entries"))
    srt_written = False
    if has_sub:
        _write_srt(os.path.splitext(out)[0] + ".srt", vp)
        srt_written = True

    applied = {"subtitles": [], "highlight": None, "cta": None,
               "visible_style_signature": "none", "variation_dimensions": {}}
    fallbacks = {"subtitle_burned": False, "highlight_burned": False, "cta_burned": False,
                 "font_path": font["font_path"], "font_source": font["source"],
                 "visible_layer_enabled": bool(settings.enable_p2b_visible_layer),
                 "visible_variation_enabled": bool(settings.enable_p2b_visible_variation),
                 "visible_style_signature": "none", "variation_applied": False,
                 "variation_degraded": False, "srt": srt_written, "fallback_reason": ""}

    def _to_sub_filters(ass_paths: list) -> list:
        out_f = []
        for p in ass_paths:
            p_esc = p.replace("\\", "/").replace(":", "\\:")
            out_f.append(f"subtitles={p_esc}:force_style='FontName={os.path.basename(font['font_path'])}'")
        return out_f

    if not settings.enable_p2b_visible_layer:
        fallbacks["fallback_reason"] = "visible_layer_disabled"
        _render(src, out, plan, audio, W, H, FPS, [])
    elif not font["available"]:
        fallbacks["fallback_reason"] = "no_font"
        _render(src, out, plan, audio, W, H, FPS, [])
    else:
        variation_on = bool(settings.enable_p2b_visible_variation)
        # fallback 链（不含 drawtext）：差异化 ASS → B2 固定 ASS（保留强可感 字幕位置+CTA时长）→ 无叠加+SRT
        candidates = []
        if variation_on:
            var_style = resolve_visible_style(vp, variant_id)
            # 必改3：固定 fallback 仍承接 2 个强可感维（subtitle_alignment + cta_duration），不退化为完全同质
            fixed_carry = dict(_FIXED_STYLE)
            fixed_carry["subtitle_alignment"] = var_style["subtitle_alignment"]
            fixed_carry["cta_duration"] = var_style["cta_duration"]
            fixed_carry["signature"] = "fixed_carry"
            candidates = [("variation", var_style, ""),
                          ("fixed_ass", fixed_carry, "degraded_to_fixed_ass"),
                          ("none", None, "degraded_to_none")]
        else:
            candidates = [("fixed_ass", _FIXED_STYLE, ""), ("none", None, "degraded_to_none")]

        for name, style, reason in candidates:
            text_dir = tempfile.mkdtemp()
            if style is None:
                ov, layers, applied_all = [], {"subtitle": [], "highlight": [], "cta": []}, \
                    {"subtitles": [], "highlight": None, "cta": None,
                     "visible_style_signature": "none", "variation_dimensions": {}}
            else:
                layers, applied_all = _build_overlays(vp, font["font_path"], target, text_dir, style)
                ov = _to_sub_filters(layers["subtitle"] + layers["highlight"] + layers["cta"])
            try:
                _render(src, out, plan, audio, W, H, FPS, ov)
            except subprocess.CalledProcessError:
                continue
            fallbacks["subtitle_burned"] = bool(layers["subtitle"])
            fallbacks["highlight_burned"] = bool(layers["highlight"])
            fallbacks["cta_burned"] = bool(layers["cta"])
            fallbacks["fallback_reason"] = reason
            fallbacks["variation_applied"] = (name == "variation")
            fallbacks["variation_degraded"] = (name != "variation")
            fallbacks["visible_style_signature"] = applied_all.get("visible_style_signature", "none")
            applied = applied_all
            break

    # B2.5：音频/编码合规差异化（第二趟，audio-only，-c:v copy，不改时长/不变速/不变调）
    if os.path.exists(out):
        _apply_audio_encoding(out, audio_enc)

    qa = qa_checks.run_gates(out, batch_md5, lo, hi, tol)
    qa["audio_encoding"] = audio_enc          # 记录到 run_items.qa_json.audio_encoding（service 写 qa_json）
    return {"ok": qa["final_status"] == "pass", "qa": qa, "plan": plan,
            "applied": applied, "fallbacks": fallbacks, "audio_encoding": audio_enc}
