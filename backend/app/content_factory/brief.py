"""Brief 理解层 — 解析与批量输入。

设计依据：M1 W1 服务骨架 + Claude Code V2 Patch B。

本层职责边界：
- 从字典/JSON 结构解析 Brief 对象；
- 批量 Brief 输入；
- 验证 task_type / target_platform / line 合法性、raw_text 非空；
- direction_hint 不得进入 used_materials，不得作为事实源；
- 不得发起任何网络调用。
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend.app.model_router.schemas import TaskType

from .schemas import Brief, VALID_TARGET_PLATFORMS, M1_LOCKED_LINE


class BriefParseError(ValueError):
    """Brief 解析失败。"""


class InvalidPlatformError(BriefParseError):
    """目标平台不合法。"""


# 合法 task_type 值集合（从 TaskType 枚举动态获取）
_VALID_TASK_TYPES = {t.value for t in TaskType}


def parse_brief(raw: Dict[str, Any]) -> Brief:
    """从字典解析 Brief。

    必填字段：raw_text（非空字符串）, target_platform（四选一）
    可选字段：task_type / line / direction_hint / target_audience / risk_hint / batch_id / extra
    """
    if not isinstance(raw, dict):
        raise BriefParseError("Brief 输入必须是字典")

    raw_text = raw.get("raw_text")
    if not raw_text or not isinstance(raw_text, str) or not raw_text.strip():
        raise BriefParseError("raw_text 不得为空")

    task_type_str = raw.get("task_type", TaskType.FACT_STRICT.value)
    if task_type_str not in _VALID_TASK_TYPES:
        raise BriefParseError(
            f"非法 task_type: {task_type_str}，合法值: {sorted(_VALID_TASK_TYPES)}"
        )
    task_type = TaskType(task_type_str)

    # target_platform 必填 + 四选一
    target_platform = raw.get("target_platform")
    if not target_platform:
        raise BriefParseError(
            f"target_platform 必填，合法值: {sorted(VALID_TARGET_PLATFORMS)}"
        )
    if target_platform not in VALID_TARGET_PLATFORMS:
        raise InvalidPlatformError(
            f"非法 target_platform: {target_platform}，合法值: {sorted(VALID_TARGET_PLATFORMS)}"
        )

    # line 默认锁死 M1_LOCKED_LINE，非 brand_dfd 拒绝
    line = raw.get("line", M1_LOCKED_LINE)
    if line != M1_LOCKED_LINE:
        raise BriefParseError(
            f"M1 锁死品牌线 {M1_LOCKED_LINE}，当前 line={line} 被拒绝"
        )

    # direction_hint 可选
    direction_hint = raw.get("direction_hint")

    return Brief(
        raw_text=raw_text.strip(),
        task_type=task_type,
        target_platform=target_platform,
        line=line,
        direction_hint=direction_hint,
        target_audience=raw.get("target_audience"),
        risk_hint=raw.get("risk_hint"),
        batch_id=raw.get("batch_id"),
        extra=raw.get("extra", {}),
    )


def parse_batch_briefs(raw_list: List[Dict[str, Any]]) -> List[Brief]:
    """批量解析 Brief 列表。

    自动分配统一的 batch_id（如未指定）。
    任一 Brief 解析失败 → 抛 BriefParseError，附带索引。
    """
    import uuid
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    results: List[Brief] = []

    for idx, raw in enumerate(raw_list):
        try:
            brief = parse_brief(raw)
            if not brief.batch_id:
                brief.batch_id = batch_id
            results.append(brief)
        except BriefParseError as e:
            raise BriefParseError(f"Brief[{idx}] 解析失败: {e}") from e

    return results
