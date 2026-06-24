"""B台 · 混剪裂变引擎（纯本地 FFmpeg，零 AI API 调用，零成本）。

B9 架构修正：
- A台 = 火山豆包视频2.0（花钱出母视频）
- B台 = 纯本地 ffmpeg 裂变（切片→去重重组→叠加策略文案/CTA→门店差异化），0元/条

输入：母视频**本地文件路径**（非 URL）。不经过 utils.video_provider。
引擎纯净：不碰 DB；产出本地 mp4 路径列表，由 service 落库与归档。
"""

from __future__ import annotations

import glob
import os
import subprocess
import tempfile
import uuid
from typing import Any

from b_engine.strategies import STRATEGIES, build_structure, pick_strategy

# ECS 需装中文字体：apt install -y fonts-wqy-zenhei
_FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

# 每策略切片节奏（秒）：引流/获客快节奏，成交/IP 慢一点
_SLICE_SECONDS = {"引流型": 3, "成交型": 5, "IP型": 5, "招商型": 4, "获客型": 3}


def _store_version(store: dict | None) -> str:
    if not store:
        return ""
    return f"{store['city']}版" if store.get("city") else f"{store['name']}版"


def _font() -> str | None:
    return _FONT if os.path.exists(_FONT) else None


def _probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return 0.0


def _slice(src: str, seg_len: int, tmpdir: str) -> list[str]:
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-c", "copy", "-f", "segment",
         "-segment_time", str(seg_len), "-reset_timestamps", "1",
         os.path.join(tmpdir, "seg_%03d.mp4")],
        check=True, capture_output=True, timeout=120,
    )
    return sorted(glob.glob(os.path.join(tmpdir, "seg_*.mp4")))


def _concat(paths: list[str], out: str) -> None:
    lst = out + ".txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out],
            check=True, capture_output=True, timeout=120,
        )
    finally:
        if os.path.exists(lst):
            os.remove(lst)


def _esc(text: str) -> str:
    return text.replace("\\", "").replace(":", "：").replace("'", "").replace('"', "")


def _render_variant(src: str, out: str, index: int, top_text: str, cta_text: str) -> None:
    """对（已重组的）视频做去重 crop + 叠加策略文案/CTA，输出最终 mp4。"""
    pad = 2 + (index % 4) * 2  # 轻微裁切，逐条不同 → 去重
    vf = f"crop=iw-{2 * pad}:ih-{2 * pad}:{pad}:{pad}"
    font = _font()
    if font:
        vf += (
            f",drawtext=fontfile='{font}':text='{_esc(top_text)}':fontcolor=white:"
            f"fontsize=36:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=30"
            f",drawtext=fontfile='{font}':text='{_esc(cta_text)}':fontcolor=yellow:"
            f"fontsize=40:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=h-text_h-40"
        )
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", vf, "-pix_fmt", "yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy", out]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except subprocess.CalledProcessError:
        # 兜底：滤镜失败则直接转封装一份（仍产出有效 mp4，不 crash）
        subprocess.run(["ffmpeg", "-y", "-i", src, "-c", "copy", out],
                       check=True, capture_output=True, timeout=120)


def remix_videos(
    tenant_id: str,
    source_path: str,
    count: int,
    prompt: str | None = None,
    strategy: str | None = "mix",
    stores: list[dict] | None = None,
    output_dir: str | None = None,
) -> list[dict[str, Any]]:
    """纯本地 ffmpeg 裂变 count 条。source_path 为母视频本地文件路径。

    返回 [{local_path, title, strategy, store_id, duration, units(=0), meta}]。
    """
    if not source_path or not os.path.exists(source_path):
        raise ValueError(f"母视频本地文件不存在：{source_path}")
    out_dir = output_dir or tempfile.mkdtemp()
    os.makedirs(out_dir, exist_ok=True)
    total_dur = _probe_duration(source_path)

    outputs: list[dict[str, Any]] = []
    for i in range(count):
        skey = pick_strategy(i, strategy)
        strat = STRATEGIES[skey]
        store = stores[i % len(stores)] if stores else None
        version = _store_version(store)
        seg_len = _SLICE_SECONDS.get(skey, 4)

        out = os.path.join(out_dir, f"{uuid.uuid4().hex}.mp4")
        work = source_path
        tmpdir = None
        # 切片 + 重组（去重）：仅当时长够切多段
        if total_dur >= 2 * seg_len:
            tmpdir = tempfile.mkdtemp()
            segs = _slice(source_path, seg_len, tmpdir)
            if len(segs) >= 2:
                k = i % len(segs)
                recombined = os.path.join(tmpdir, "recombined.mp4")
                _concat(segs[k:] + segs[:k], recombined)
                work = recombined

        top_text = f"{version}{strat['label']}".strip() or strat["label"]
        _render_variant(work, out, i, top_text, strat["cta"])

        changes = {
            "strategy": skey,
            "goal": strat["goal"],
            "hook": strat["hook"],
            "ending": strat["cta"],
            "structure": build_structure(prompt, strat),
            "store_version": version,
            "subtitle": f"{version}{strat['label']}·{(prompt or strat['goal'])}",
            "engine": "local_ffmpeg",
        }
        outputs.append({
            "local_path": out,
            "title": changes["subtitle"],
            "strategy": skey,
            "store_id": store["id"] if store else None,
            "duration": _probe_duration(out),
            "units": 0,                       # 本地处理，0 成本
            "meta": {"changes": changes, "provider": "local_ffmpeg"},
        })
    return outputs
