"""G4 四平台结构规则集契约（W7）。

设计依据：M1-W7 条件施工许可 二.4。

四出口各一套 PlatformRuleSet（结构裁决细则）。骨架期沿用 W4 结构标记，
结构上支持外置/版本化/md5 签收（复用 RulePack 承载）。
G4 只判结构——非结构问题路由到 G1/G2/G3/G5（契约层重申，不在此裁决）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

VALID_PLATFORMS = ["brand_site", "xiaohongshu", "douyin", "shipinhao"]


@dataclass
class PlatformRuleSet:
    """单平台结构规则集契约。"""

    platform: str
    required_sections: List[str] = field(default_factory=list)   # 缺 → FAIL
    optional_sections: List[str] = field(default_factory=list)   # 缺 → WARNING
    version: str = "0.1.0"
    is_mock: bool = True
    notes: str = ""


def platform_rulesets() -> Dict[str, PlatformRuleSet]:
    """四平台结构规则集（platform → PlatformRuleSet）。"""
    return {
        "brand_site": PlatformRuleSet(
            "brand_site",
            required_sections=["标题", "正文"],
            optional_sections=["FAQ", "SEO摘要", "AI答案块", "内链建议"],
            notes="品牌站 SEO/GEO 资产稿结构",
        ),
        "xiaohongshu": PlatformRuleSet(
            "xiaohongshu",
            required_sections=["标题", "正文", "标签"],
            optional_sections=["封面建议"],
            notes="小红书图文/种草结构",
        ),
        "douyin": PlatformRuleSet(
            "douyin",
            required_sections=["钩子", "口播"],
            optional_sections=["分镜", "结尾引导"],
            notes="抖音口播稿结构",
        ),
        "shipinhao": PlatformRuleSet(
            "shipinhao",
            required_sections=["开场", "正文"],
            optional_sections=["金句", "评论引导"],
            notes="视频号口播稿结构",
        ),
    }
