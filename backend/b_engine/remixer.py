"""B台 · 混剪裂变引擎（纯本地 FFmpeg，零 AI API 调用，零成本）。

V4 P1.1 修复（短视频裂变）：
- 废弃旧 _slice()(-c copy -f segment) + _concat()(concat -c copy) + _render_variant() 中 -c:a copy。
  这三处是 14 秒卡死 / PTS 损坏 / 音视频失步 / MD5 重复的根源。
- 新流程：全程重编码，trim+setpts / atrim+asetpts / filter_complex 安全拼接，
  统一 fps/scale/SAR/采样率，movflags +faststart，输出 duration 控制在 [lo,hi]（默认 25-35）。
- 多维差异化（段序/组合/字幕/轻色调/轻裁切/淡入），视觉手段叠加 ≤2，不做廉价炫酷。
- 四道 hard QA（duration/pts/playable/md5）+ 失败自动重试 + partial_done（失败不入 outputs）。
- 第一版禁止任何 -c copy 快路径。

输入：母视频**本地文件路径**。引擎纯净：不碰 DB；产出本地 mp4 路径列表，由 service 落库归档。
对外返回结构保持兼容（local_path/title/strategy/store_id/duration/units/meta），QA 信息放 meta["qa"]。
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
import uuid
from typing import Any

from b_engine import qa_checks
from b_engine.strategies import STRATEGIES, build_structure, pick_strategy
from config import settings

# ECS 需装中文字体：apt install -y fonts-wqy-zenhei
_FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

# V4 P1.1 Audio Click/Pop Hotfix：音频切割点微淡入淡出，消除波形硬跳变产生的 click/pop。
# 默认 30ms（人耳几乎不可感知，可有效消除 click）；极短片段（<120ms）跳过 fade，
# 且 fade 时长不超过片段的 1/4，防止 in/out fade 重叠。测试可 monkeypatch 这两个常量取 20/50ms 样片。
_AUDIO_FADE = 0.03           # 默认微淡时长（秒）= 30ms
_AUDIO_FADE_MIN_SEG = 0.12   # 短于此（120ms）的片段跳过 fade


def _store_version(store: dict | None) -> str:
    if not store:
        return ""
    return f"{store['city']}版" if store.get("city") else f"{store['name']}版"


def _font() -> str | None:
    return _FONT if os.path.exists(_FONT) else None


def _esc(text: str) -> str:
    return (text or "").replace("\\", "").replace(":", "：").replace("'", "").replace('"', "")


def _probe_duration(path: str) -> float:
    return qa_checks.probe_duration(path)


def _drawtext(font: str, text: str, color: str, size: int, y: str) -> str:
    return (
        f"drawtext=fontfile='{font}':text='{_esc(text)}':fontcolor={color}:"
        f"fontsize={size}:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y={y}"
    )


def _build_variant(src: str, out: str, seed: int, dur: float, audio: bool,
                   target: float, top_text: str, cta_text: str) -> None:
    """单次 ffmpeg：trim+setpts/atrim+asetpts → filter_complex concat → 差异化叠加 →
    -t target 重编码输出。全程重编码，无 -c copy。"""
    W, H, FPS = settings.b_remix_width, settings.b_remix_height, settings.b_remix_fps
    pad = 2 + (seed % 5) * 2                       # 轻微裁切（差异化①，视觉手段）
    sat = round(0.92 + (seed % 9) * 0.02, 3)       # 轻色调饱和（差异化②，视觉手段）
    bri = round(-0.03 + (seed % 7) * 0.01, 3)
    font = _font()

    norm = (f"setpts=PTS-STARTPTS,fps={FPS},"
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1")

    inputs: list[str] = []
    fc_parts: list[str] = []

    if dur >= 9.0:
        # LONG：三段重排（段序/组合差异化），重复列表直到累计 ≥ target
        thirds = [(0.0, dur / 3), (dur / 3, 2 * dur / 3), (2 * dur / 3, dur)]
        rot = seed % 3
        order = thirds[rot:] + thirds[:rot]
        windows: list[tuple[float, float]] = []
        total = 0.0
        idx = 0
        while total < target + 1.0 and idx < 64:
            w = order[idx % 3]
            windows.append(w)
            total += (w[1] - w[0])
            idx += 1
        inputs = ["-i", src]
        v_labels, a_labels = [], []
        for k, (s, e) in enumerate(windows):
            fc_parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},{norm}[v{k}]")
            v_labels.append(f"[v{k}]")
            if audio:
                # 音频微淡入淡出（hotfix）：消除切割点 click/pop。
                seg_dur = max(e - s, 0.0)
                fade_d = min(_AUDIO_FADE, seg_dur / 4)
                if seg_dur >= _AUDIO_FADE_MIN_SEG and fade_d > 0:
                    out_st = max(seg_dur - fade_d, 0.0)
                    fc_parts.append(
                        f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                        f"aresample=async=1:first_pts=0,"
                        f"afade=t=in:st=0:d={fade_d:.3f},"
                        f"afade=t=out:st={out_st:.3f}:d={fade_d:.3f}[a{k}]")
                else:
                    # 极短片段：不加 fade，避免 fade 时长超过片段本身
                    fc_parts.append(
                        f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                        f"aresample=async=1:first_pts=0[a{k}]")
                a_labels.append(f"[a{k}]")
        n = len(windows)
        fc_parts.append("".join(v_labels) + f"concat=n={n}:v=1:a=0[vc]")
        if audio:
            fc_parts.append("".join(a_labels) + f"concat=n={n}:v=0:a=1[ac]")
    else:
        # SHORT：stream_loop 整段补足，单流规范化（差异化靠叠加层 + 时长）
        loops = max(0, math.ceil((target + 1.0) / max(dur, 0.3)) - 1)
        inputs = ["-stream_loop", str(loops), "-i", src]
        fc_parts.append(f"[0:v]{norm}[vc]")
        if audio:
            # SHORT 为整段 stream_loop，不做 segment 级 fade；首尾加全局微 fade，
            # 防止循环接缝处 click（out fade 起点用 f-string 正确注入 target）。
            if _AUDIO_FADE > 0:
                out_st = max(target - _AUDIO_FADE, 0.0)
                fc_parts.append(
                    f"[0:a]asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0,"
                    f"afade=t=in:st=0:d={_AUDIO_FADE:.3f},"
                    f"afade=t=out:st={out_st:.3f}:d={_AUDIO_FADE:.3f}[ac]")
            else:
                fc_parts.append("[0:a]asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0[ac]")

    # 无音轨 → 用 anullsrc 补静音（保证可拼/可播放）
    if not audio:
        inputs += ["-f", "lavfi", "-t", f"{target + 1.0:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        a_map_idx = "[1:a]" if dur >= 9.0 else "[1:a]"
        fc_parts.append(f"{a_map_idx}atrim=0:{target:.2f},asetpts=PTS-STARTPTS[ac]")

    # 差异化叠加：裁切 + 色调（视觉手段 ≤2） + 淡入(轻转场) + 策略字幕/CTA（文字）
    overlay = f"[vc]crop=iw-{2 * pad}:ih-{2 * pad}:{pad}:{pad},eq=saturation={sat}:brightness={bri},fade=t=in:st=0:d=0.3"
    if font:
        overlay += "," + _drawtext(font, top_text, "white", 36, "30")
        overlay += "," + _drawtext(font, cta_text, "yellow", 40, "h-text_h-40")
    overlay += "[vout]"
    fc_parts.append(overlay)

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc_parts),
           "-map", "[vout]", "-map", "[ac]", "-t", f"{target:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "aac", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)


def remix_videos(
    tenant_id: str,
    source_path: str,
    count: int,
    prompt: str | None = None,
    strategy: str | None = "mix",
    stores: list[dict] | None = None,
    output_dir: str | None = None,
) -> list[dict[str, Any]]:
    """纯本地 ffmpeg 裂变 count 条短视频（全程重编码 + QA + 重试 + partial_done）。

    返回**仅通过 QA**的 outputs（兼容旧结构）；失败条不入 outputs，统计放 meta["qa"]/日志。
    """
    if not source_path or not os.path.exists(source_path):
        raise ValueError(f"母视频本地文件不存在：{source_path}")
    out_dir = output_dir or tempfile.mkdtemp()
    os.makedirs(out_dir, exist_ok=True)
    dur = _probe_duration(source_path)
    audio = qa_checks.has_audio(source_path)

    lo = settings.b_remix_target_lo
    hi = settings.b_remix_target_hi
    tol = settings.b_remix_duration_tol
    max_retry = settings.b_remix_max_retry
    batch_md5: set[str] = set()

    outputs: list[dict[str, Any]] = []
    failed = 0
    for i in range(count):
        skey = pick_strategy(i, strategy)
        strat = STRATEGIES[skey]
        store = stores[i % len(stores)] if stores else None
        version = _store_version(store)
        top_text = f"{version}{strat['label']}".strip() or strat["label"]
        cta_text = strat["cta"]

        qa = None
        produced = None
        used_seed = None
        attempts = 0
        # 目标时长在 [lo,hi] 内按变体取值（也作差异化）
        for attempt in range(max_retry + 1):
            attempts = attempt
            seed = i * 131 + attempt * 977
            used_seed = seed
            span = max(0.0, hi - lo)
            target = round(lo + ((seed * 7) % 1000) / 1000.0 * span, 2) if span > 0 else lo
            out = os.path.join(out_dir, f"{uuid.uuid4().hex}.mp4")
            try:
                _build_variant(source_path, out, seed, dur, audio, target, top_text, cta_text)
            except subprocess.CalledProcessError:
                if os.path.exists(out):
                    os.remove(out)
                continue
            qa = qa_checks.run_gates(out, batch_md5, lo, hi, tol)
            if qa["final_status"] == "pass":
                produced = out
                break
            if os.path.exists(out):       # 失败产物删除，换 seed 重试
                os.remove(out)

        if produced is None:
            failed += 1
            continue                       # partial_done：失败不入 outputs
        batch_md5.add(qa["md5"])

        changes = {
            "strategy": skey, "goal": strat["goal"], "hook": strat["hook"], "ending": strat["cta"],
            "structure": build_structure(prompt, strat), "store_version": version,
            "subtitle": f"{version}{strat['label']}·{(prompt or strat['goal'])}",
            "engine": "local_ffmpeg",
        }
        outputs.append({
            "local_path": produced,
            "title": changes["subtitle"],
            "strategy": skey,
            "store_id": store["id"] if store else None,
            "duration": _probe_duration(produced),
            "units": 0,
            "meta": {
                "changes": changes, "provider": "local_ffmpeg",
                "qa": {                    # ★ P1.1：QA 信息放兼容位置 meta["qa"]
                    "duration_ok": qa["duration_ok"], "pts_ok": qa["pts_ok"],
                    "playable_ok": qa["playable_ok"], "md5": qa["md5"],
                    "md5_duplicate": qa["md5_duplicate"], "final_status": qa["final_status"],
                    "retry_count": attempts, "logs": qa["logs"],
                },
                "variant_seed": used_seed,
            },
        })

    # 批级汇总放最后一条 meta（不改返回类型；旧 b_service 忽略即可）
    if outputs:
        outputs[-1]["meta"]["qa_summary"] = {
            "requested": count, "passed": len(outputs), "failed": failed,
            "partial_done": failed > 0,
        }
    return outputs
