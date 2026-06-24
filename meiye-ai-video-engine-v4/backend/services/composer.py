"""P0：长视频编排 + FFmpeg 拼接。

一次成型：用户输入长视频需求 → 拆分镜（按 5/10/15s 切片）→ 各片段生成 → 下载本地
→ FFmpeg concat 拼接 → 输出完整成片。

分镜拆解默认规则化（无 LLM 依赖，可后续替换为 LLM 拆解器，接口不变）。
真实片段由 provider 生成；本模块负责「切片规划 + 拼接」，可独立验证（用真实 mp4 文件拼接）。
"""

from __future__ import annotations

import math
import os
import subprocess
import uuid


def plan_segments(total_seconds: int, segment_seconds: int = 5) -> list[int]:
    """把总时长切成若干等长片段。例：120s / 5 = 24×5s；120/15=8×15s。"""
    segment_seconds = max(1, segment_seconds)
    n = max(1, math.ceil(total_seconds / segment_seconds))
    return [segment_seconds] * n


def segment_options(total_seconds: int) -> dict:
    """长视频切片预设：主 15s / 备 10s / 裂变 5s。返回各方案 segments list。
    例 120s → {"main":[15×8], "backup":[10×12], "viral":[5×24]}。"""
    return {
        "main": plan_segments(total_seconds, 15),
        "backup": plan_segments(total_seconds, 10),
        "viral": plan_segments(total_seconds, 5),
    }


def split_storyboard(prompt: str, n: int) -> list[str]:
    """分镜拆解（规则版）：把一句话拆成 n 个分镜提示。可替换为 LLM 拆解器。"""
    parts = [p.strip() for p in prompt.replace("，", "。").split("。") if p.strip()]
    out: list[str] = []
    for i in range(n):
        base = parts[i % len(parts)] if parts else prompt
        out.append(f"{base}（镜头{i + 1}/{n}）")
    return out


def ffmpeg_concat(segment_paths: list[str], output_path: str) -> str:
    """用 FFmpeg concat demuxer 把多个 mp4 无损拼接成一条。返回 output_path。"""
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
            check=True, capture_output=True,
        )
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)
    return output_path


def compose_long_video(
    tenant_id: str,
    prompt: str,
    total_seconds: int,
    segment_seconds: int,
    output_dir: str = "./storage/videos",
    segment_generator=None,
) -> dict:
    """编排：切片 → 逐段生成（segment_generator(tenant_id, seg_prompt, seconds)->本地mp4路径）
    → FFmpeg 拼接 → 输出。segment_generator 由上层注入（接 provider+下载），便于解耦与测试。
    """
    seg_lens = plan_segments(total_seconds, segment_seconds)
    prompts = split_storyboard(prompt, len(seg_lens))
    if segment_generator is None:
        raise ValueError("需注入 segment_generator（接 provider 生成并下载片段）")

    seg_paths: list[str] = []
    for seg_prompt, seconds in zip(prompts, seg_lens):
        seg_paths.append(segment_generator(tenant_id, seg_prompt, seconds))

    os.makedirs(output_dir, exist_ok=True)
    output = os.path.join(output_dir, f"long_{uuid.uuid4().hex}.mp4")
    ffmpeg_concat(seg_paths, output)
    return {
        "segments": len(seg_paths),
        "segment_seconds": segment_seconds,
        "total_seconds": total_seconds,
        "output_path": output,
    }
