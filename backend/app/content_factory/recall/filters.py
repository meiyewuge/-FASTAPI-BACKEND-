"""白名单 / 黑名单过滤 — 素材类型准入控制（fail-closed）。

设计依据：M1 W2 9080 只读召回适配 + Claude Code V2 Patch C。

fail-closed 原则：
- material_type 缺失 → 拒绝
- source_type 缺失 → 拒绝或 blocked
- status 缺失 → blocked/conditional，不得默认放行

默认白名单：fact_card / compliance_rule / style_template / engine_asset
默认黑名单：含 M1 明确禁入/慎入素材类型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── 默认白名单（允许的 material_type）─────────────────────────────────
DEFAULT_WHITELIST = [
    "fact_card",
    "compliance_rule",
    "style_template",
    "engine_asset",
]

# ── 默认黑名单（排除的 material_type 或 source 标记）──────────────────
# Patch C: 补入 M1 明确禁入/慎入素材类型
DEFAULT_BLACKLIST = [
    "draft",
    "rejected",
    "archived",
    "raw_draft",
    "kimi_expansion",            # Kimi 扩写件不得作为事实材料
    "daily_brief",               # DAILY_*
    "daily_report",              # DAILY_*
    "webintel",                  # WEBINTEL_*
    "webintel_crawl",            # WEBINTEL_*
    "crawl_raw",                 # crawl_*
    "crawl_unverified",          # crawl_*
    "craft_memory",              # 工艺记忆不得作为事实
    "platform_inspiration_as_fact",  # 平台灵感不得当事实
]


def apply_filters(
    materials: List[Dict[str, Any]],
    whitelist: Optional[List[str]] = None,
    blacklist: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """对素材列表应用白名单 + 黑名单过滤（fail-closed）。

    fail-closed 原则：
    - material_type 缺失 → 拒绝（不进 used_materials）
    - source_type 缺失 → 拒绝
    - status 缺失 → blocked（不进 used_materials）
    - 白名单：material_type 必须在白名单中
    - 黑名单：material_type 或 status 在黑名单中则排除
    """
    wl = whitelist if whitelist is not None else DEFAULT_WHITELIST
    bl = blacklist if blacklist is not None else DEFAULT_BLACKLIST

    result: List[Dict[str, Any]] = []
    for m in materials:
        mtype = m.get("material_type", m.get("type", ""))
        mstatus = m.get("status", "")
        msource = m.get("source_type", "")

        # fail-closed: material_type 缺失 → 拒绝
        if not mtype:
            continue

        # fail-closed: source_type 缺失 → 拒绝
        if not msource:
            continue

        # fail-closed: status 缺失 → 拒绝
        if not mstatus:
            continue

        # 白名单过滤：material_type 必须在白名单中（空白名单=不过滤）
        if wl and mtype not in wl:
            continue

        # 黑名单过滤：material_type 或 status 在黑名单中则排除
        if bl and (mtype in bl or mstatus in bl):
            continue

        result.append(m)
    return result


@dataclass
class FilterReport:
    """过滤报告 — 记录过滤前后的数量变化。"""

    before_count: int
    after_count: int
    whitelist_applied: List[str] = field(default_factory=list)
    blacklist_applied: List[str] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return self.before_count - self.after_count


def apply_filters_with_report(
    materials: List[Dict[str, Any]],
    whitelist: Optional[List[str]] = None,
    blacklist: Optional[List[str]] = None,
) -> tuple:
    """过滤并返回 (filtered_materials, FilterReport)。"""
    wl = whitelist if whitelist is not None else DEFAULT_WHITELIST
    bl = blacklist if blacklist is not None else DEFAULT_BLACKLIST
    filtered = apply_filters(materials, wl, bl)
    report = FilterReport(
        before_count=len(materials),
        after_count=len(filtered),
        whitelist_applied=list(wl),
        blacklist_applied=list(bl),
    )
    return filtered, report
