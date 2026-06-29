"""V4 P2B-B3 三维差异评分闸门（只评分，不自动重剪/不生成/不扩批）。

按 V1.1 施工包实现：
- 视觉(visual,40)：关键帧 pHash/dHash + 取窗 overlap + 镜头结构差。
- 文本(text,35)：applied_json 文本编辑距离 + 位置档位差 + visible_style_signature 档位差（OCR 仅可见性交叉校验，非主输入）。
- 音频(audio,15)：audio_encoding_signature / EQ profile 差（辅助维，不单独否决；fp_diff 留接口不启用）。
- 质量(quality,10)：loudness/true_peak/clipping/playback/pts/duration，硬闸；判定线复用 B2.5 外部验收线 TP≤-1
  （**B2.5 内部 TP=-2 是处理目标，不是 B3 判定线**）。
- VDS=visual+ocr+audio+quality(∈[0,100])；pairwise 两两矩阵；recommended_action 仅三值；
  商业指标 effective_variant_count / batch_pass_rate；权重 40/35/15/10 含滞后切换 45/35/10/10。

纯本地、零成本：抽帧仅 ffmpeg 取单帧降采样灰度 raw（不重编码、不生成新 mp4、不跑完整视频）；
pHash/dHash 纯 Python 实现（无 numpy/PIL 依赖）。大 N 模拟为 metadata-only（不渲染）。
"""

from __future__ import annotations

import math
import subprocess
from itertools import combinations

# ---- 权重档（visual, text, audio, quality）----
WEIGHTS_DEFAULT = (40.0, 35.0, 15.0, 10.0)
WEIGHTS_LOW_AUDIO = (45.0, 35.0, 10.0, 10.0)

# 质量判定线（与 B2.5 外部验收线对齐）
LUFS_LO, LUFS_HI = -15.0, -13.0     # -14 ±1
TP_ACCEPT_DBTP = -1.0               # 外部验收线（非内部 -2 处理目标）
DUR_LO, DUR_HI = 25.0, 35.0

_HASH_BITS = 64


# ============================ 关键帧抽样 + 指纹（纯 Python） ============================

def keyframe_times(duration: float, k: int) -> list[float]:
    """V1.1 抽帧区间：t_i = 0.1*d + 0.8*d*(i+0.5)/K，避开片头/片尾黑帧/logo/统一 CTA 收尾帧。"""
    if not duration or duration <= 0 or k <= 0:
        return []
    return [round(0.1 * duration + 0.8 * duration * (i + 0.5) / k, 3) for i in range(k)]


def _extract_gray(path: str, t: float, w: int, h: int) -> list[int] | None:
    """ffmpeg 取单帧 → 降采样到 w×h 灰度 raw（w*h 字节）。失败/无文件 → None。不生成新 mp4。"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
             "-frames:v", "1", "-vf", f"scale={w}:{h}:flags=area,format=gray",
             "-f", "rawvideo", "-"],
            capture_output=True, timeout=30,
        )
        buf = r.stdout
        if len(buf) < w * h:
            return None
        return list(buf[:w * h])
    except Exception:  # noqa: BLE001  抽帧失败不拖死评分
        return None


def _dhash(gray9x8: list[int]) -> int:
    """dHash：9×8 灰度，逐行相邻像素比较 → 64 bit。"""
    bits = 0
    idx = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if gray9x8[base + col] < gray9x8[base + col + 1] else 0)
            idx += 1
    return bits


# 预computed 8×32 DCT-II 基（只取前 8 个低频，pHash 用）
_DCT_N = 32
_DCT8x32 = [[math.cos(math.pi * (2 * x + 1) * u / (2 * _DCT_N)) for x in range(_DCT_N)]
            for u in range(8)]


def _phash(gray32x32: list[int]) -> int:
    """pHash：32×32 灰度 → 2D DCT 取左上 8×8 低频，对中位数取阈 → 64 bit。纯 Python DCT。"""
    X = [gray32x32[r * _DCT_N:(r + 1) * _DCT_N] for r in range(_DCT_N)]
    # tmp[u][x2] = Σ_x D[u][x] * X[x][x2]  → 8×32
    tmp = [[0.0] * _DCT_N for _ in range(8)]
    for u in range(8):
        Du = _DCT8x32[u]
        for x2 in range(_DCT_N):
            s = 0.0
            for x in range(_DCT_N):
                s += Du[x] * X[x][x2]
            tmp[u][x2] = s
    # coef[u][v] = Σ_x2 tmp[u][x2] * D[v][x2]  → 8×8
    coef = [[0.0] * 8 for _ in range(8)]
    for u in range(8):
        for v in range(8):
            Dv = _DCT8x32[v]
            row = tmp[u]
            s = 0.0
            for x2 in range(_DCT_N):
                s += row[x2] * Dv[x2]
            coef[u][v] = s
    vals = [coef[u][v] for u in range(8) for v in range(8)]
    # 中位数排除 DC([0][0])，避免被直流主导
    ac = sorted(vals[1:])
    med = ac[len(ac) // 2]
    bits = 0
    for val in vals:
        bits = (bits << 1) | (1 if val > med else 0)
    return bits


def frame_hashes(path: str, duration: float, k: int) -> list[tuple[int, int]] | None:
    """抽 K 帧 → 每帧 (phash, dhash)。任一帧抽取失败即返回 None（触发视觉代理）。"""
    times = keyframe_times(duration, k)
    if not times:
        return None
    out = []
    for t in times:
        g32 = _extract_gray(path, t, 32, 32)
        g98 = _extract_gray(path, t, 9, 8)
        if g32 is None or g98 is None:
            return None
        out.append((_phash(g32), _dhash(g98)))
    return out


def _ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _frame_dist(h1: tuple[int, int], h2: tuple[int, int]) -> float:
    return 0.5 * _ham(h1[0], h2[0]) / _HASH_BITS + 0.5 * _ham(h1[1], h2[1]) / _HASH_BITS


# ============================ 视觉维度 ============================

def _interval_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    lo = max(a[0], b[0]); hi = min(a[1], b[1])
    inter = max(0.0, hi - lo)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else (1.0 if inter > 0 else 0.0)


def _edit_seq(a: list, b: list) -> int:
    """序列编辑距离（角色序列 / 转场序列）。"""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return max(m, n)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def structural_window_diff(win_a: list[dict], win_b: list[dict]) -> float:
    """同 role 取窗时间区间 IoU → 1 - mean(IoU)。无可比 role → 视为最大差异 1.0。"""
    if not win_a or not win_b:
        return 1.0
    by_a: dict[str, list] = {}
    by_b: dict[str, list] = {}
    for w in win_a:
        by_a.setdefault(w.get("role", "?"), []).append((float(w["start"]), float(w["end"])))
    for w in win_b:
        by_b.setdefault(w.get("role", "?"), []).append((float(w["start"]), float(w["end"])))
    ious = []
    for role in set(by_a) & set(by_b):
        la, lb = by_a[role], by_b[role]
        for i in range(min(len(la), len(lb))):
            ious.append(_interval_iou(la[i], lb[i]))
    if not ious:
        return 1.0
    return round(1.0 - sum(ious) / len(ious), 4)


def shot_structure_diff(struct_a: dict, struct_b: dict) -> float:
    """镜头结构差：窗口数差 + role 序列编辑距离 + 转场类型序列差，三者均值（归一）。"""
    wa, wb = struct_a.get("windows") or [], struct_b.get("windows") or []
    ta = [t.get("xfade", "") for t in (struct_a.get("transitions") or [])]
    tb = [t.get("xfade", "") for t in (struct_b.get("transitions") or [])]
    n_max = max(len(wa), len(wb), 1)
    count_diff = abs(len(wa) - len(wb)) / n_max
    role_a = [w.get("role", "?") for w in wa]
    role_b = [w.get("role", "?") for w in wb]
    role_diff = _edit_seq(role_a, role_b) / n_max
    t_max = max(len(ta), len(tb), 1)
    trans_diff = _edit_seq(ta, tb) / t_max
    return round((count_diff + role_diff + trans_diff) / 3.0, 4)


def visual_pair(a: dict, b: dict, visual_target: float) -> dict:
    """视觉维度（每 pair）。有真帧 → pHash/dHash；无真帧 → structural proxy（visual_proxy_only=True）。"""
    sw_diff = structural_window_diff(a.get("windows") or [], b.get("windows") or [])
    ss_diff = shot_structure_diff(a, b)
    fa, fb = a.get("frame_hashes"), b.get("frame_hashes")
    if fa and fb and len(fa) == len(fb) and len(fa) > 0:
        per = [_frame_dist(fa[i], fb[i]) for i in range(len(fa))]
        kf_visual = sum(per) / len(per)
        kf_min = min(per)
        visual_distance = 0.55 * kf_visual + 0.30 * sw_diff + 0.15 * ss_diff
        proxy = False
    else:
        # 视觉代理：无像素帧，用结构差代理 kf；明确标记 proxy（结论只可读作 structure_only_risk）
        kf_visual = None
        kf_min = None
        visual_distance = 0.70 * sw_diff + 0.30 * ss_diff
        proxy = True
    return {
        "kf_visual": round(kf_visual, 4) if kf_visual is not None else None,
        "kf_min": round(kf_min, 4) if kf_min is not None else None,
        "structural_window_diff": sw_diff, "shot_structure_diff": ss_diff,
        "visual_distance": round(visual_distance, 4),
        "visual_proxy_only": proxy,
        "visual_score": round(_clip01(visual_distance / visual_target) * WEIGHTS_DEFAULT[0], 3),
    }


# ============================ 文本维度 ============================

def _levenshtein(a: str, b: str) -> int:
    a, b = a or "", b or ""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return max(m, n)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        ca = a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def _norm_lev(a: str, b: str) -> float:
    a, b = a or "", b or ""
    mx = max(len(a), len(b))
    return 0.0 if mx == 0 else _levenshtein(a, b) / mx


def _join_texts(items) -> str:
    """把 applied subtitle/highlight/cta 的文本拼成一串（顺序稳定）。"""
    if items is None:
        return ""
    if isinstance(items, dict):
        return str(items.get("text", "") or "")
    if isinstance(items, list):
        return " ".join(str((it or {}).get("text", "") or "") for it in items)
    return str(items)


_STRONG_SIG_DIMS = ("subtitle_alignment", "cta_style", "highlight_time_bucket")


def _sig_dim_count(sig: str) -> int:
    """visible_style_signature 形如 sa0mv1fs2ol0ha1ht2ca0cs3cd1 → 9 维。"""
    return 9


def text_pair(a: dict, b: dict, text_target: float) -> dict:
    """文本维度（每 pair）：applied_json 文本（主）+ 位置档位差 + signature 档位差。OCR 仅交叉校验，不入分。"""
    d_sub = _norm_lev(_join_texts(a.get("subtitle_applied")), _join_texts(b.get("subtitle_applied")))
    d_hl = _norm_lev(_join_texts(a.get("highlight_applied")), _join_texts(b.get("highlight_applied")))
    d_cta = _norm_lev(_join_texts(a.get("cta_applied")), _join_texts(b.get("cta_applied")))
    text_core = (d_sub + d_hl + d_cta) / 3.0

    dims_a = a.get("variation_dimensions") or {}
    dims_b = b.get("variation_dimensions") or {}
    # 位置差：alignment / margin 档位
    pos_keys = ("subtitle_alignment", "highlight_alignment", "cta_alignment",
                "subtitle_margin_v", "cta_duration_bucket")
    pos_difs = [1.0 if dims_a.get(k) != dims_b.get(k) else 0.0
                for k in pos_keys if k in dims_a or k in dims_b]
    pos_diff = sum(pos_difs) / len(pos_difs) if pos_difs else 0.0

    sig_a, sig_b = a.get("visible_style_signature", ""), b.get("visible_style_signature", "")
    if dims_a and dims_b:
        keys = set(dims_a) | set(dims_b)
        diff_keys = [k for k in keys if dims_a.get(k) != dims_b.get(k)]
        strong_hit = sum(1 for k in diff_keys if k in _STRONG_SIG_DIMS)
        sig_diff = len(diff_keys) / max(len(keys), 1)
        # 强可感维度加权（每命中一个强维 +0.1，封顶 1.0）
        sig_diff_weighted = min(1.0, sig_diff + 0.1 * strong_hit)
    else:
        sig_diff = 0.0 if sig_a == sig_b else 1.0
        sig_diff_weighted = sig_diff

    text_distance = 0.45 * text_core + 0.25 * pos_diff + 0.30 * sig_diff_weighted
    return {
        "d_sub": round(d_sub, 4), "d_hl": round(d_hl, 4), "d_cta": round(d_cta, 4),
        "pos_diff": round(pos_diff, 4), "sig_diff": round(sig_diff, 4),
        "sig_diff_weighted": round(sig_diff_weighted, 4),
        "text_distance": round(text_distance, 4),
        "all_text_equal": (d_sub == 0 and d_hl == 0 and d_cta == 0),
        "ocr_score": round(_clip01(text_distance / text_target) * WEIGHTS_DEFAULT[1], 3),
    }


# ============================ 音频维度（辅助，不单独否决） ============================

def audio_pair(a: dict, b: dict, audio_target: float) -> dict:
    """音频差异（每 pair）：EQ profile 差 + signature 字段差。fp_diff 留接口不启用。"""
    eq_diff = 1.0 if (a.get("eq_profile") != b.get("eq_profile")) else 0.0
    sa = (a.get("audio_encoding_signature") or "").split("|")
    sb = (b.get("audio_encoding_signature") or "").split("|")
    fields = max(len(sa), len(sb), 1)
    same = sum(1 for i in range(min(len(sa), len(sb))) if sa[i] == sb[i])
    sig_diff_audio = 1.0 - same / fields
    audio_distance = 0.6 * eq_diff + 0.4 * sig_diff_audio
    return {
        "eq_diff": round(eq_diff, 4), "sig_diff_audio": round(sig_diff_audio, 4),
        "fp_diff": None,  # 第一版留接口不启用
        "audio_distance": round(audio_distance, 4),
        "audio_score": round(_clip01(audio_distance / audio_target) * WEIGHTS_DEFAULT[2], 3),
    }


# ============================ 质量维度（per-variant，硬闸） ============================

def quality_variant(v: dict) -> dict:
    """每条自身质量安全项。优先读 meta/qa 字段；缺失才由调用方提供实测值（measured）。判定线 TP≤-1。"""
    ae = v.get("audio_encoding") or {}
    measured = v.get("measured") or {}
    qa = v.get("qa") or {}
    lufs = measured.get("lufs", ae.get("measured_lufs", ae.get("integrated_lufs")))
    tp = measured.get("true_peak", ae.get("measured_tp", ae.get("true_peak")))

    checks = {}
    # loudness / true_peak：有实测才判；无实测时若 B2.5 applied 则按"处理已保证"标 None→不否决但记 unknown
    if lufs is not None:
        checks["loudness_ok"] = (LUFS_LO <= float(lufs) <= LUFS_HI)
    else:
        checks["loudness_ok"] = None
    if tp is not None:
        checks["true_peak_ok"] = (float(tp) <= TP_ACCEPT_DBTP)
        checks["clipping_ok"] = (float(tp) <= 0.0)
    else:
        checks["true_peak_ok"] = None
        checks["clipping_ok"] = None
    checks["playback_ok"] = qa.get("playable_ok")
    checks["pts_ok"] = qa.get("pts_ok")
    dur = v.get("duration")
    checks["duration_ok"] = (DUR_LO <= float(dur) <= DUR_HI) if dur is not None else None

    known = [val for val in checks.values() if val is not None]
    passed = sum(1 for val in known if val)
    score = round(WEIGHTS_DEFAULT[3] * (passed / len(known)), 3) if known else WEIGHTS_DEFAULT[3]
    quality_fail = any(val is False for val in checks.values())
    return {**checks, "quality_score": score, "quality_fail": quality_fail,
            "lufs": lufs, "true_peak": tp}


# ============================ 权重滞后切换 ============================

def decide_weights(audio_distance_mean: float, previous_profile: str | None,
                   low: float, high: float) -> dict:
    """滞后区间：<low → low_audio(45/35/10/10)；>high → default(40/35/15/10)；区间内保持上次（无则 default）。"""
    band = [low, high]
    if audio_distance_mean < low:
        prof, reason = "low_audio", f"audio_distance_mean={audio_distance_mean:.4f} < {low} → 45/35/10/10"
    elif audio_distance_mean > high:
        prof, reason = "default", f"audio_distance_mean={audio_distance_mean:.4f} > {high} → 40/35/15/10"
    else:
        if previous_profile in ("low_audio", "default"):
            prof = previous_profile
            reason = (f"audio_distance_mean={audio_distance_mean:.4f} ∈ [{low},{high}] 滞后区间 → "
                      f"保持上次 {prof}")
        else:
            prof = "default"
            reason = (f"audio_distance_mean={audio_distance_mean:.4f} ∈ [{low},{high}] 且无历史 → 默认 default")
    weights = WEIGHTS_LOW_AUDIO if prof == "low_audio" else WEIGHTS_DEFAULT
    return {"weight_profile": prof, "weights": list(weights),
            "weight_switch_reason": reason, "hysteresis_band": band,
            "audio_distance_mean": round(audio_distance_mean, 4)}


# ============================ pairwise + batch 评分 ============================

def _clip01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _rescale_scores(visual_d, text_d, audio_d, q_score, weights, targets) -> tuple:
    vt, tt, at = targets
    vs = _clip01(visual_d / vt) * weights[0]
    os_ = _clip01(text_d / tt) * weights[1]
    aus = _clip01(audio_d / at) * weights[2]
    return round(vs, 3), round(os_, 3), round(aus, 3), round(q_score / WEIGHTS_DEFAULT[3] * weights[3], 3)


def score_pair(a: dict, b: dict, thr: dict, weights: list) -> dict:
    targets = (thr["visual_target"], thr["text_target"], thr["audio_target"])
    vis = visual_pair(a, b, thr["visual_target"])
    txt = text_pair(a, b, thr["text_target"])
    aud = audio_pair(a, b, thr["audio_target"])
    q_min = min(a["_quality"]["quality_score"], b["_quality"]["quality_score"])
    quality_fail = a["_quality"]["quality_fail"] or b["_quality"]["quality_fail"]

    vs, os_, aus, qs = _rescale_scores(vis["visual_distance"], txt["text_distance"],
                                       aud["audio_distance"], q_min, weights, targets)
    vds = round(vs + os_ + aus + qs, 3)

    too_similar_visual = (vis["kf_min"] is not None and vis["kf_min"] < thr["kf_min_floor"])
    too_similar_text = txt["all_text_equal"] and txt["sig_diff"] == 0.0
    flags = []
    if too_similar_visual:
        flags.append("too_similar_visual")
    if too_similar_text:
        flags.append("too_similar_text")
    if quality_fail:
        flags.append("quality_fail")
    if vis["visual_proxy_only"]:
        flags.append("visual_proxy_only")

    # pair 状态分类
    below_floor = (vis["visual_distance"] < thr["visual_floor"] or txt["text_distance"] < thr["text_floor"])
    if quality_fail or too_similar_visual or too_similar_text or vds < (thr["vds_pass"] - 5):
        status = "regen"
    elif vds < thr["vds_pass"] or below_floor:
        status = "review"
    else:
        status = "pass"

    return {
        "pair": [a["video_id"], b["video_id"]],
        "group_pair": [a.get("group_type"), b.get("group_type")],
        **{k: vis[k] for k in ("kf_visual", "kf_min", "structural_window_diff",
                               "shot_structure_diff", "visual_distance", "visual_proxy_only")},
        **{k: txt[k] for k in ("d_sub", "d_hl", "d_cta", "pos_diff", "sig_diff",
                               "sig_diff_weighted", "text_distance", "all_text_equal")},
        **{k: aud[k] for k in ("eq_diff", "sig_diff_audio", "fp_diff", "audio_distance")},
        "visual_score": vs, "ocr_score": os_, "audio_score": aus, "quality_score": qs,
        "VDS_total": vds, "pair_pass": status == "pass", "pair_status": status,
        "pair_flags": flags,
    }


def _action_from_statuses(statuses: list[str]) -> str:
    if any(s == "regen" for s in statuses):
        return "needs_regeneration_later"
    if any(s == "review" for s in statuses):
        return "manual_review"
    return "pass_to_publish_pool"


def score_batch(videos: list[dict], thr: dict, previous_weight_profile: str | None = None) -> dict:
    """对一个 batch（建议 3 条；N≤fullpair_max_n 全量 pairwise）评分。videos 已含 frame_hashes/windows/applied/signatures。

    返回 batch 结果（pairwise_matrix / per_variant / batch_summary 含商业指标 / thresholds_used）。
    """
    for v in videos:
        v["_quality"] = quality_variant(v)

    # 先用默认权重算一遍 audio_distance，决定权重档（滞后）
    base_audio = [audio_pair(a, b, thr["audio_target"])["audio_distance"]
                  for a, b in combinations(videos, 2)]
    audio_mean = sum(base_audio) / len(base_audio) if base_audio else 0.0
    wd = decide_weights(audio_mean, previous_weight_profile,
                        thr["audio_switch_low"], thr["audio_switch_high"])
    weights = wd["weights"]

    matrix = [score_pair(a, b, thr, weights) for a, b in combinations(videos, 2)]

    # 每 variant 聚合：取其参与 pair 的状态/分
    per_variant = []
    for v in videos:
        vid = v["video_id"]
        mypairs = [c for c in matrix if vid in c["pair"]]
        statuses = [c["pair_status"] for c in mypairs]
        action = _action_from_statuses(statuses)
        if v["_quality"]["quality_fail"]:
            action = "needs_regeneration_later"
        vds_list = [c["VDS_total"] for c in mypairs] or [0.0]
        reasons = sorted({f for c in mypairs for f in c["pair_flags"]})
        if v["_quality"]["quality_fail"]:
            reasons = sorted(set(reasons) | {"quality_fail"})
        per_variant.append({
            "video_id": vid, "group_type": v.get("group_type"),
            "visual_score": round(sum(c["visual_score"] for c in mypairs) / len(mypairs), 3) if mypairs else 0.0,
            "ocr_score": round(sum(c["ocr_score"] for c in mypairs) / len(mypairs), 3) if mypairs else 0.0,
            "audio_score": round(sum(c["audio_score"] for c in mypairs) / len(mypairs), 3) if mypairs else 0.0,
            "quality_score": v["_quality"]["quality_score"],
            "VDS_total": round(min(vds_list), 3),   # 取最坏 pair 作为该条 VDS
            "pass": action == "pass_to_publish_pool",
            "fail_reason": reasons,
            "recommended_action": action,
        })

    total = len(videos)
    effective = sum(1 for p in per_variant if p["recommended_action"] == "pass_to_publish_pool")
    too_similar_pairs = [c["pair"] for c in matrix if ("too_similar_visual" in c["pair_flags"]
                                                       or "too_similar_text" in c["pair_flags"])]
    min_vds = min((c["VDS_total"] for c in matrix), default=0.0)
    weakest = min(matrix, key=lambda c: c["VDS_total"])["pair"] if matrix else []
    visual_covered = all(c["visual_distance"] >= thr["visual_floor"] for c in matrix)
    ocr_covered = all(c["text_distance"] >= thr["text_floor"] for c in matrix)
    audio_covered = all(c["audio_distance"] > 0 for c in matrix)
    batch_pass = all(c["pair_pass"] for c in matrix)
    batch_action = _action_from_statuses([c["pair_status"] for c in matrix])

    fail_reasons = sorted({f for c in matrix for f in c["pair_flags"]})
    if not visual_covered:
        fail_reasons.append("visual_below_floor")
    if not ocr_covered:
        fail_reasons.append("text_below_floor")

    return {
        "batch_id": None,  # 由 service 填 run_id
        "video_ids": [v["video_id"] for v in videos],
        "pairwise_matrix": matrix,
        "per_variant": per_variant,
        "batch_summary": {
            "min_pair_VDS": round(min_vds, 3), "weakest_pair": weakest,
            "too_similar_pairs": too_similar_pairs,
            "visual_covered": visual_covered, "ocr_covered": ocr_covered, "audio_covered": audio_covered,
            "pass": batch_pass, "fail_reason": sorted(set(fail_reasons)),
            "recommended_action": batch_action,
            "total_variant_count": total,
            "effective_variant_count": effective,
            "batch_pass_rate": round(effective / total, 4) if total else 0.0,
        },
        "thresholds_used": {
            "VDS_pass": thr["vds_pass"], "visual_floor": thr["visual_floor"],
            "text_floor": thr["text_floor"], "kf_min_floor": thr["kf_min_floor"],
            "weights": weights, "weight_profile": wd["weight_profile"],
            "weight_switch_reason": wd["weight_switch_reason"],
            "audio_distance_mean": wd["audio_distance_mean"], "hysteresis_band": wd["hysteresis_band"],
            "VISUAL_TARGET": thr["visual_target"], "TEXT_TARGET": thr["text_target"],
            "AUDIO_TARGET": thr["audio_target"],
            "calibration": thr["calibration"],
        },
        "b3_version": thr["b3_version"],
        "deterministic": True,
    }


# ============================ 大 N 模拟（metadata-only，不渲染） ============================

def _sig_prefix_bucket(v: dict) -> str:
    """强可感 3 维分桶键（sa/cs/ht）：同强可感三元组的更易撞车。"""
    sig = v.get("visible_style_signature", "")
    # 形如 sa#mv#fs#ol#ha#ht#ca#cs#cd#，提取 sa/ht/cs
    def _g(tag):
        i = sig.find(tag)
        return sig[i + len(tag)] if i >= 0 and i + len(tag) < len(sig) else "?"
    return f"sa{_g('sa')}ht{_g('ht')}cs{_g('cs')}"


def _window_bucket(v: dict, grid: float = 2.0) -> str:
    """取窗起点量化分桶（粗格 grid 秒）。"""
    wins = v.get("windows") or []
    return "|".join(f"{w.get('role','?')}:{int(float(w.get('start',0))/grid)}" for w in wins[:4])


def bucket_candidates(videos: list[dict]) -> dict:
    """O(N) 分桶 → 候选对（同桶取并集）。N>fullpair_max_n 时启用，避免全量 O(N²)。"""
    by_sig: dict[str, list] = {}
    by_win: dict[str, list] = {}
    by_group: dict[str, list] = {}
    for idx, v in enumerate(videos):
        by_sig.setdefault(_sig_prefix_bucket(v), []).append(idx)
        by_win.setdefault(_window_bucket(v), []).append(idx)
        by_group.setdefault(v.get("group_type", "?"), []).append(idx)

    candidates: set[tuple[int, int]] = set()
    hotspots = []
    for bucket_map, kind in ((by_sig, "sig"), (by_win, "window"), (by_group, "group")):
        for key, members in bucket_map.items():
            if len(members) > 1:
                if len(members) >= 3:
                    hotspots.append({"bucket_kind": kind, "bucket_key": key, "size": len(members)})
                for i, j in combinations(members, 2):
                    candidates.add((min(i, j), max(i, j)))
    # 跨 group 抽样比对（每 group 取代表，互比，降低无谓精算）
    reps = [members[0] for members in by_group.values()]
    for i, j in combinations(reps, 2):
        candidates.add((min(i, j), max(i, j)))

    bucket_density = {
        "sig_buckets": len(by_sig), "window_buckets": len(by_win), "group_buckets": len(by_group),
        "max_sig_bucket": max((len(m) for m in by_sig.values()), default=0),
        "max_window_bucket": max((len(m) for m in by_win.values()), default=0),
    }
    return {"candidates": sorted(candidates), "hotspots": hotspots, "bucket_density": bucket_density,
            "by_sig": by_sig}


def simulate_large_n(videos: list[dict], thr: dict, full_pair_max_n: int) -> dict:
    """大 N metadata-only 模拟：检测 signature 重复 / 档位撞车 / too_similar 候选对密度。不渲染、不生成视频。

    视觉用 structural proxy（visual_proxy_only=True）；仅当候选对的视频已有真实可抽帧文件时做 pixel 校准
    （高风险桶 top-2 pair），记 pixel_verified。无真实帧 → pixel_verified=0，结论只可读作 structure_only_risk。
    """
    n = len(videos)
    vis_sigs = [v.get("visible_style_signature", "") for v in videos]
    aud_sigs = [v.get("audio_encoding_signature", "") for v in videos]

    def _dups(seq):
        seen, dup = set(), 0
        for s in seq:
            if s in seen:
                dup += 1
            seen.add(s)
        return dup

    visible_dup = _dups(vis_sigs)
    audio_dup = _dups(aud_sigs)
    signature_dup = _dups([f"{a}#{b}" for a, b in zip(vis_sigs, aud_sigs)])

    # pairwise 策略：N≤max → 全量；N>max → 分桶候选
    if n <= full_pair_max_n:
        cand_pairs = list(combinations(range(n), 2))
        downgrade = False
        bucket_info = {"bucket_density": None, "hotspots": []}
    else:
        bc = bucket_candidates(videos)
        cand_pairs = [tuple(p) for p in bc["candidates"]]
        downgrade = True
        bucket_info = bc

    # 候选对精算（结构 + 文本 + 音频；视觉=proxy）
    too_similar = 0
    structure_only_risk = 0
    pixel_verified_risk = 0
    visual_proxy_only_count = 0
    pixel_verified_candidate_count = 0
    # 选高风险桶 top-2 pair 做像素校准（仅当有真实帧文件）
    pixel_targets = set()
    for hs in bucket_info.get("hotspots", [])[:10]:
        members = bucket_info.get("by_sig", {}).get(hs["bucket_key"], [])
        for i, j in list(combinations(members, 2))[:2]:
            pixel_targets.add((min(i, j), max(i, j)))

    for i, j in cand_pairs:
        a, b = videos[i], videos[j]
        sw = structural_window_diff(a.get("windows") or [], b.get("windows") or [])
        ss = shot_structure_diff(a, b)
        proxy_visual = 0.70 * sw + 0.30 * ss
        txt = text_pair(a, b, thr["text_target"])
        # 像素校准（仅有真实帧时）
        pixel_done = False
        if (i, j) in pixel_targets and a.get("frame_hashes") and b.get("frame_hashes"):
            fa, fb = a["frame_hashes"], b["frame_hashes"]
            if len(fa) == len(fb) and fa:
                per = [_frame_dist(fa[k], fb[k]) for k in range(len(fa))]
                proxy_visual = 0.55 * (sum(per) / len(per)) + 0.30 * sw + 0.15 * ss
                pixel_done = True
        if pixel_done:
            pixel_verified_candidate_count += 1
        else:
            visual_proxy_only_count += 1
        is_too_similar = (proxy_visual < thr["visual_floor"] or txt["text_distance"] < thr["text_floor"])
        if is_too_similar:
            too_similar += 1
            if pixel_done:
                pixel_verified_risk += 1
            else:
                structure_only_risk += 1

    return {
        "N": n,
        "candidate_pair_count": len(cand_pairs),
        "full_pairs_if_naive": n * (n - 1) // 2,
        "downgrade_applied": downgrade,
        "signature_duplicate_count": signature_dup,
        "visible_signature_duplicate_count": visible_dup,
        "audio_signature_duplicate_count": audio_dup,
        "too_similar_candidate_count": too_similar,
        "structure_only_risk": structure_only_risk,
        "pixel_verified_risk": pixel_verified_risk,
        "visual_proxy_only_count": visual_proxy_only_count,
        "pixel_verified_candidate_count": pixel_verified_candidate_count,
        "bucket_density": bucket_info.get("bucket_density"),
        "collision_hotspots": bucket_info.get("hotspots", []),
        "unique_visible_signatures": len(set(vis_sigs)),
        "unique_audio_signatures": len(set(aud_sigs)),
        "note": ("structure_only_risk 为 metadata 结构代理结论，非完整视觉查重；"
                 "pixel_verified_risk 才是抽真帧 pHash/dHash 校准结论。无真实帧时 pixel_verified=0。"),
    }
