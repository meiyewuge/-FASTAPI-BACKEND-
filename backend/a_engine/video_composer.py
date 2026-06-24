"""B6：长视频多段拼接。

Seedance 2.0 单段最长 15s；长视频需切多段生成后 FFmpeg 拼接成完整成片。
本模块只负责「切片规划 + 分镜拆解 + FFmpeg 拼接编排」，片段如何生成由上层注入
segment_generator（接 provider + 下载到本地），便于解耦与独立验证。

约束：禁止 import b_engine；不碰 DB。依赖 ECS 已装 ffmpeg。
"""

from __future__ import annotations

import os
import subprocess
import uuid
from typing import Callable


def plan_segments(total_seconds: int, max_seg: int = 15) -> list[int]:
    """把总时长切成若干 ≤max_seg 的片段。例：40s → [15,15,10]；120s → 8×15。"""
    total = max(1, int(total_seconds))
    max_seg = max(1, int(max_seg))
    segs: list[int] = []
    rem = total
    while rem > 0:
        s = min(max_seg, rem)
        segs.append(s)
        rem -= s
    return segs


def split_storyboard(prompt: str, n: int) -> list[str]:
    """分镜拆解（规则版，可替换为 LLM）：把一句话拆成 n 个分镜提示。"""
    parts = [p.strip() for p in prompt.replace("，", "。").split("。") if p.strip()]
    return [f"{(parts[i % len(parts)] if parts else prompt)}（镜头{i + 1}/{n}）" for i in range(n)]


def ffmpeg_concat(segment_paths: list[str], output_path: str) -> str:
    """FFmpeg concat demuxer 无损拼接多个 mp4。返回 output_path。"""
    if not segment_paths:
        raise ValueError("无片段可拼接")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    list_file = f"{output_path}.concat.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
             "-c", "copy", output_path],
            check=True, capture_output=True, timeout=300,
        )
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)
    return output_path


def compose_long_video(
    tenant_id: str,
    prompt: str,
    total_seconds: int,
    resolution: str,
    segment_generator: Callable[[str, str, int, str], str],
    output_dir: str,
    max_seg: int = 15,
) -> dict:
    """编排：切片 → 逐段生成(注入的 segment_generator 返回本地 mp4 路径) → FFmpeg 拼接 → 输出。

    segment_generator(tenant_id, seg_prompt, seconds, resolution) -> 本地 mp4 路径
    """
    seg_lens = plan_segments(total_seconds, max_seg)
    prompts = split_storyboard(prompt, len(seg_lens))
    seg_paths = [segment_generator(tenant_id, p, secs, resolution) for p, secs in zip(prompts, seg_lens)]

    os.makedirs(output_dir, exist_ok=True)
    output = os.path.join(output_dir, f"long_{uuid.uuid4().hex}.mp4")
    ffmpeg_concat(seg_paths, output)
    return {
        "segments": len(seg_paths),
        "segment_seconds": seg_lens,
        "total_seconds": sum(seg_lens),
        "output_path": output,
    }
