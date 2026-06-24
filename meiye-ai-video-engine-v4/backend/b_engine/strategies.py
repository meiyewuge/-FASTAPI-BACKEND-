"""B台内容策略库（商业内容模型，模板驱动、零 LLM）。

把 B台从「技术混剪」升级为「商业内容生成器」：
- 内容策略分型：引流型 / 成交型 / IP型 / 招商型 / 获客型
- 情绪结构：痛点开头 → 冲突推进 → 解决方案 → 行动引导
- 门店差异化：同一母视频 → 各门店/城市版本
"""

from __future__ import annotations

# 5 种商业内容策略：每种 = 开头钩子 + 行动号召(CTA) + 目标
STRATEGIES: dict[str, dict] = {
    "引流型": {"label": "引流型", "hook": "痛点疑问开头", "cta": "关注解锁更多干货", "goal": "涨粉引流"},
    "成交型": {"label": "成交型", "hook": "效果前后对比开头", "cta": "到店即享限时优惠", "goal": "促进成交"},
    "IP型": {"label": "IP型", "hook": "主理人故事/人设开头", "cta": "关注主理人", "goal": "塑造IP"},
    "招商型": {"label": "招商型", "hook": "数据/加盟案例开头", "cta": "私信咨询加盟政策", "goal": "招商加盟"},
    "获客型": {"label": "获客型", "hook": "到店福利开头", "cta": "扫码预约到店体验", "goal": "门店获客"},
}

STRATEGY_KEYS = list(STRATEGIES.keys())

# 情绪结构 4 拍（固定骨架）
EMOTION_BEATS = ["痛点开头", "冲突推进", "解决方案", "行动引导"]


def pick_strategy(index: int, strategy: str | None) -> str:
    """strategy='mix'/None → 轮换 5 型；指定某型 → 用该型（非法回落引流型）。"""
    if not strategy or strategy == "mix":
        return STRATEGY_KEYS[index % len(STRATEGY_KEYS)]
    return strategy if strategy in STRATEGIES else "引流型"


def build_structure(theme: str | None, strat: dict) -> list[str]:
    """按情绪结构 4 拍生成分镜骨架（模板填充，非 LLM）。"""
    topic = theme or strat["goal"]
    return [
        f"痛点开头：{strat['hook']}（聚焦「{topic}」）",
        "冲突推进：放大问题、制造对比张力",
        f"解决方案：给出「{topic}」方案与效果证明",
        f"行动引导：{strat['cta']}",
    ]
