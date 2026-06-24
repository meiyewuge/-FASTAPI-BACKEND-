"""B台 · 混剪裂变引擎（商业内容生成器）。

链路：母视频 → 切片 → 重组 → 套用内容策略(分型+情绪结构+门店差异化) → 输出 count 条裂变视频。
约束：禁止 import a_engine；视频能力经 utils.video_provider。
引擎保持纯净：不碰 DB，stores 以普通 dict 传入，返回数据 + 成本列表，由 service 落库与记账。
"""

from __future__ import annotations

from typing import Any

from b_engine.strategies import STRATEGIES, build_structure, pick_strategy
from utils.video_provider import get_provider


def _store_version(store: dict | None) -> str:
    if not store:
        return ""
    return f"{store['city']}版" if store.get("city") else f"{store['name']}版"


def remix_videos(
    tenant_id: str,
    source_url: str,
    count: int,
    prompt: str | None = None,
    strategy: str | None = "mix",
    stores: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """基于母视频批量产出 count 条裂变视频。

    - strategy: 'mix'(默认轮换5型) 或 引流型/成交型/IP型/招商型/获客型
    - stores: [{id, name, city}]，用于门店差异化与归因（可空）
    """
    provider = get_provider()
    outputs: list[dict[str, Any]] = []
    for i in range(count):
        skey = pick_strategy(i, strategy)
        strat = STRATEGIES[skey]
        store = stores[i % len(stores)] if stores else None
        version = _store_version(store)

        changes = {
            "strategy": skey,
            "goal": strat["goal"],
            "hook": strat["hook"],
            "ending": strat["cta"],
            "structure": build_structure(prompt, strat),
            "store_version": version,
            "subtitle": f"{version}{strat['label']}·{(prompt or strat['goal'])}",
        }
        r = provider.remix(tenant_id, source_url, i, changes)
        outputs.append(
            {
                "title": changes["subtitle"],
                "strategy": skey,
                "store_id": store["id"] if store else None,
                "url": r["url"],
                "duration": r.get("duration"),
                "cost": r["cost"],
                "meta": {"changes": changes, **r.get("meta", {})},
            }
        )
    return outputs
