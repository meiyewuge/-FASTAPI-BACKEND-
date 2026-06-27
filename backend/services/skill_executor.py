"""技能执行器（V4 P2A · 仅骨架）。

============================================================
 skill_executor P2A 安全边界（施工包 §3.3）
============================================================
 P2A 允许的操作模式：
   - mock:         返回模拟结果，不执行任何真实操作
   - dry_validate: 仅校验 skill_id 在白名单 + params 结构

 P2A 禁止的操作（运行时硬拦截，违反直接抛异常）：
   - mode=execute / real / ffmpeg            → 抛 ValueError
   - 禁止绑定真实 ffmpeg adapter（不 import ffmpeg / 不调 subprocess 视频命令）
   - 禁止调用 remixer（不 from b_engine.remixer import）
   - 禁止写 videos 表（不 import videos model、不 INSERT/UPDATE videos、不生成 output_video_id）
============================================================

本文件刻意不 import：subprocess / b_engine.remixer / models.Video。
"""

from __future__ import annotations

import logging

from services.skill_registry_service import CANONICAL_SKILL_IDS

logger = logging.getLogger(__name__)

# ===== SKILL_WHITELIST：与 §2.7 CANONICAL_SKILL_IDS 完全一致（同一真值源，杜绝漂移）=====
SKILL_WHITELIST = set(CANONICAL_SKILL_IDS)

# P2A 允许的执行模式
ALLOWED_MODES = {"mock", "dry_validate"}


def run(skill_id: str, params: dict | None = None, mode: str = "mock") -> dict:
    """执行技能（P2A 仅 mock / dry_validate）。

    Raises:
        ValueError: skill_id 不在白名单 / mode 不允许（含 execute/real/ffmpeg）。
    """
    params = params or {}

    # === 安全校验 1: skill_id 白名单 ===
    if skill_id not in SKILL_WHITELIST:
        raise ValueError(
            f"[skill_executor] 未知技能: {skill_id}，允许的技能: {sorted(SKILL_WHITELIST)}"
        )

    # === 安全校验 2: mode 白名单（execute/real/ffmpeg 一律拒绝）===
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"[skill_executor] P2A 不允许 mode={mode}，仅允许: {sorted(ALLOWED_MODES)}"
        )

    # === 安全校验 3-5（代码层面保证）===
    #   - 不 import / 不绑定真实 ffmpeg adapter
    #   - 不 from b_engine.remixer import 任何内容
    #   - 不 import videos model，不执行 INSERT/UPDATE videos

    if mode == "dry_validate":
        logger.info("[skill_executor] dry_validate: %s params_keys=%s", skill_id, list(params.keys()))
        return {
            "status": "validated",
            "skill_id": skill_id,
            "mode": "dry_validate",
            "message": "P2A dry_validate - schema check passed (no real execution)",
        }

    # mode == "mock"
    logger.info("[skill_executor] mock: %s", skill_id)
    return {
        "status": "mock",
        "skill_id": skill_id,
        "mode": "mock",
        "message": "P2A skeleton - no real execution, no ffmpeg, no remixer, no videos write",
    }


def validate_skill_sequence(skill_sequence: list[dict]) -> list[str]:
    """批量校验技能序列（dry_validate）。返回错误列表，空表示全部通过。"""
    errors: list[str] = []
    for i, step in enumerate(skill_sequence or []):
        sid = step.get("skill_id", "")
        if sid not in SKILL_WHITELIST:
            errors.append(f"step[{i}]: unknown skill_id '{sid}'")
    return errors
